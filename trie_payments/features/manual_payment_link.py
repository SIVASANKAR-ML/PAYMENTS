import frappe, re
import requests
import json
from trie_payments.external_form_payment_functions import generating_the_order_no_for_payment,generating_the_hash_for_payment_authentication

@frappe.whitelist(allow_guest= True)
def send_payment_link(invoice_id,site_name,is_subscription):
    if not invoice_id:
        raise ValueError(f"No invoice id")
    # check if the invoice is in Draft
    invoice=frappe.get_doc("Sales Invoice",invoice_id)
    # if(invoice.status != "Draft"):
    #     raise ValueError(f"Invoice is not in draft")
    # create an order id and insert it into invoice order number field
    customer=frappe.get_doc("Customer",invoice.customer)
    mobile_no=customer.custom_mobile_number
    if not mobile_no:
        raise ValueError(f"Invalid customer mobile number")
    # creating whatsapp customer or else returning existing customer
    details={
        "mobile_no":mobile_no
    }
    whatsapp_customer=create_whatsapp_customer(details)
    subscription=frappe.get_doc("Subscription",invoice.subscription)

    # Always mint a fresh order number for THIS attempt. Reusing a prior
    # attempt's order number let two Draft Sales Invoices share the same
    # custom_order_id, so the payment webhook could resolve the wrong
    # (stale-dated) invoice on a resend.
    order_number=generating_the_order_no_for_payment(mobile_no,site_name)
    # adding two decimal places for totalpay
    order_amount= str("{:.2f}".format(invoice.rounded_total or invoice.grand_total))
    # request body
    body={
        "customer_name":customer.customer_name,
        "mobile_no":mobile_no,
        "order_number":order_number,
        "amount":order_amount,
        "description":"Trie TotalPay Payment Manual",
        "site_name":site_name,
        "currency":invoice.currency
    }
    # get payment link
    response=creating_payment_url(body,is_subscription,invoice_id)
    payment_url=response["url"]["redirect_url"]
    # Tag THIS invoice so the webhook can match it unambiguously.
    invoice.custom_order_id=order_number
    invoice.save(ignore_permissions=True)

    # subscription.custom_order_number is the anchor TotalPay's own recurring
    # engine correlates auto-charge webhooks against. Set it once, at the
    # very first link (recurring_init) — never overwrite it on a resend, or
    # the anchor drifts from what TotalPay has on file and the next genuine
    # auto-charge webhook can no longer find this subscription.
    if not subscription.custom_order_number:
        subscription.custom_order_number=order_number
    subscription.custom_payment_link_url=payment_url
    subscription.save(ignore_permissions=True)
    
    # calling the whatsapp sales invoice sending function after updating the location of the vehicle
    try:
        apps = frappe.get_single("Installed Applications").installed_applications
        app_array = [app.app_name for app in apps if app.app_name in ["trie_whatsapp", "trie_crm"]]
        if app_array:
            # send whatsapp message and sms to user
            from trie_whatsapp.sms_actions import send_payment_url_manual_customer
            send_payment_url_manual_customer(mobile_no, payment_url)
            
            from trie_whatsapp.whatsapp_templates import send_payment_url
            response= send_payment_url(mobile_no, payment_url)
            if response and "messages" in response and response["messages"]:
                status = response["messages"][0]["message_status"]
                return status
            else:
                frappe.log_error("Invalid response from send_payment_url", response)
                return "failed"
    except Exception as e:
        frappe.log_error("Error on sending whatsapp payment link", e)
        return "failed"

def create_whatsapp_customer(details):
    is_customer_present=frappe.db.exists("WhatsApp Customer Details",details["mobile_no"])
    if(is_customer_present):
        whatsapp_customer=frappe.get_doc("WhatsApp Customer Details",details["mobile_no"])
        return whatsapp_customer
    # creating new whatsapp customer
    whatsapp_customer=frappe.new_doc("WhatsApp Customer Details")
    whatsapp_customer.whatsapp_id=details["mobile_no"]
    whatsapp_customer.save(ignore_permissions=True)
    return whatsapp_customer

# sample body
# body={
#     order_number,
#     amount,
#     currency,
#     description,
#     customer_name,
#     mobile_no,
#     site_name,
# }
# add manual true for form validations
def creating_payment_url(body,is_subscription,invoice_id):
    site_config = frappe.get_site_config()
    global_totalpay_url = site_config.get("global_totalpay_url")
    form_url = site_config.get("external_subscription_url")
    merchant_key = site_config.get("merchant_key")
    merchant_password = site_config.get("merchant_password")
    url = f"{global_totalpay_url}/api/v1/session"

    hash=generating_the_hash_for_payment_authentication(body["order_number"],body["amount"],body["currency"],body["description"],merchant_password)
    customer_name=body["customer_name"]
    full_name = f"{customer_name}"
    cleaned_full_name = None
    if re.search(r'[^\w\s]', full_name):
        cleaned_full_name = re.sub(r'[^\w\s]', ' ', full_name)
    else:
        cleaned_full_name = full_name

    methods = ["card"] if is_subscription else ["card", "applepay"]
    # frappe.log_error("Payment Methods", f"Methods: {methods}, Recurring: {is_subscription}")

    mobile_no=body["mobile_no"]
    payload = {
      "merchant_key": f"{merchant_key}",
      "operation": "purchase",
      "methods": methods,
      "customer": {
        "birth_date": "2000-01-01",
      },
      "order": {
        "number": body["order_number"],
        "amount": body["amount"],
        "currency": body["currency"],
        "description": body["description"]
      },
      "cancel_url": f"{form_url}?payment_status=failed&manual=true",
      "success_url": f"{form_url}?payment_status=success&manual=true",
      "customer": {
        "name": cleaned_full_name,
        "email": f"{mobile_no}@trie.com"
      },
      "billing_address": {
        "phone": body["mobile_no"],
        "country": "AE",
        "state": "Dubai",
        "city": "Al Quoz",
        "district": "Al Quoz",
        "address": body["site_name"],
        "house_number": "AKG 007",
        "zip": "122002"
      },
      "req_token": is_subscription,
      "recurring_init": is_subscription,
      "hash": hash,
      "session_expiry" : 719
    }
    if not is_subscription:
        custom_data = {"one_time_payment": "True", "invoice_no": invoice_id}
        payload["custom_data"] = custom_data
    payload = json.dumps(payload)
    headers = {
      'Content-Type': 'application/json'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    json_response = frappe.utils.data.json.loads(response.text)
    frappe.log_error("json_response:",json_response)
    return {
        "hash":hash,
        "url":json_response
    }
