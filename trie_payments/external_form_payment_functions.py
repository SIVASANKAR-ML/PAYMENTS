import frappe, random
from erpnext.controllers.accounts_controller import get_taxes_and_charges
import requests
import hashlib
import json
import datetime as dt
import re
from frappe.utils import getdate, today, now, now_datetime, relativedelta
from datetime import timedelta, datetime, date
from trie_crm.utils import log_operational
from trie_whatsapp.sms_actions import payment_success, payment_failure, payment_renewal_success, payment_renewal_failure, subscription_message, send_pdf_sales_invoice

@frappe.whitelist()
def generating_payment_url(whatsapp_id, package_id):
    doc = frappe.get_doc("WhatsApp Customer Details", whatsapp_id)
    doc.package_deal = package_id
    doc.save(ignore_permissions=True)
    try:
        if doc:
            # Creating a customer
            customer_id = creating_customer_for_sales_invoice(doc, whatsapp_id, package_id)
            return customer_id
        else:
            pass
    except Exception as e:
        frappe.log_error("Error in generating payment url", e)
        pass


def creating_customer_for_sales_invoice(doc, whatsapp_id, package_id):
    try:
        # Try to find an existing customer with the given mobile number
        existing_customer = frappe.get_all("Customer", filters={"custom_mobile_number": doc.name}, limit=1)

        if existing_customer:
            customer_doc_name=frappe.get_doc("Customer",existing_customer)
            customer_name=customer_doc_name.name
            # Return the existing customer document
            getting_customer_id = frappe.get_doc("WhatsApp Customer Details", whatsapp_id)
            package_id = getting_customer_id.package_deal
            returning_url = creating_draft_sales_invoice(customer_name, package_id, whatsapp_id, doc)

            return returning_url
            
        if not existing_customer:

            # Create a new customer if none exists
            customer_name = f"{doc.first_name} {doc.last_name}"
            new_customer = frappe.new_doc("Customer")
            new_customer.customer_name = customer_name
            new_customer.custom_contract_number = "Nil - WhatsApp"
            new_customer.custom_mobile_number = doc.name
            new_customer.customer_type = "Individual"
            new_customer.customer_group = "Individual"
            new_customer.territory = "United Arab Emirates"

            if doc.car_brand_and_model == "":
                car_brand_value = doc.custom_car_brand
                car_model_value = doc.custom_car_model
                new_customer.append('custom_vehicle_information', {
                    'site_name': doc.site_name,
                    'car_type': doc.car_type,
                    'registration_number': doc.car_registration_number,
                    'other_brand_and_model': f"{car_brand_value} {car_model_value}",
                    'car_color': doc.car_color
                })
            else:
                new_customer.append('custom_vehicle_information', {
                    'site_name': doc.site_name,
                    'car_type': doc.car_type,
                    'registration_number': doc.car_registration_number,
                    'brand_and_model': doc.car_brand_and_model,
                    'car_color': doc.car_color
                })

            new_customer.save(ignore_permissions = True)

            customer_name=new_customer.name

            getting_customer_id = frappe.get_doc("WhatsApp Customer Details", whatsapp_id)
            package_id = getting_customer_id.package_deal

            returning_url = creating_draft_sales_invoice(customer_name, package_id, whatsapp_id, doc)

            try:
                if returning_url:
                    fetching_lead_docs = frappe.get_all("Lead", filters={"mobile_no": whatsapp_id}, fields=["name"])

                    for lead_doc in fetching_lead_docs:
                        getting_lead_doc = frappe.get_doc("Lead", lead_doc["name"])

                        if getting_lead_doc.custom_lead_status != "Subscribed":
                            getting_lead_doc.custom_lead_status = "Link Provided"
                            getting_lead_doc.save(ignore_permissions=True)
            except Exception as e:
                frappe.log_error("Error occurred on updating Link Provided lead status", e)

            return returning_url
        
        else:
            pass

    except Exception as e:
        frappe.log_error("Error occured on creating customer", e)


def creating_draft_sales_invoice(customer_name, package_id, whatsapp_id, doc):

    # Create a new draft Sales Invoice document
    sales_invoice_doc = frappe.new_doc("Sales Invoice")
    sales_invoice_doc.customer = customer_name
    sales_invoice_doc.status = "Draft"
    sales_invoice_doc.posting_date = frappe.utils.nowdate()
    sales_invoice_doc.naming_series = "WTSP-SINV-.YYYY.-"
    sales_invoice_doc.custom_invoice_type = "New"
    sales_invoice_doc.site_name = doc.site_name
    if doc.site_name:
        # print(doc.site_name,"doc.site_name 2")
        cost_center = frappe.db.get_value('Cost Center', {'custom_branch': doc.site_name}, 'name')
        if cost_center:
            sales_invoice_doc.cost_center = cost_center


    from trie_crm.triecrm_functions import get_income_account

    # Fetch the subscription plan rate
    subscription_plan = frappe.get_doc("Subscription Plan", package_id)
    # Paid through a payment link (card): income is booked directly, not deferred
    item = {
        'doctype': 'Sales Invoice Item',
        'item_code': package_id,
        'qty': 1,
        'rate': subscription_plan.cost,
        "enable_deferred_revenue": 0,
        "income_account": get_income_account(sales_invoice_doc.company),
        "cost_center" : cost_center
    }
    sales_invoice_doc.append('items', item)

    # Generate order ID for payment
    id_generated_value = generating_the_order_no_for_payment(whatsapp_id, doc.site_name)

    # Create a Customer Vehicle Order
    creating_new_customer_vehicle_order(id_generated_value, whatsapp_id)
    
    # Assign custom order ID to the sales invoice
    sales_invoice_doc.custom_order_id = id_generated_value

    # Insert and save the Sales Invoice
    sales_invoice_doc.insert(ignore_permissions=True)
    sales_invoice_doc.save(ignore_permissions=True)
    # frappe.db.commit()

    site_config = frappe.get_site_config()
    merchant_pass_id = site_config.get("merchant_password")
    getting_plan_rate = frappe.get_doc("Subscription Plan", package_id, fields=["cost", "currency"])
    # need to make the amount format as 09.00 not 09.0
    order_amount_hash = "{:.2f}".format(getting_plan_rate.cost)
    order_currency_hash = getting_plan_rate.currency
    order_description_hash = package_id
    # Creating a hash for payment redirect url
    generated_hashing_value = generating_the_hash_for_payment_authentication(
        id_generated_value, 
        order_amount_hash,
        order_currency_hash, 
        order_description_hash, 
        merchant_pass_id
    )

    # Payment Authentication
    whatsapp_contact_id = whatsapp_id
    first_name = doc.first_name
    last_name = doc.last_name
    # frappe.log_error("payment_type in draft invoice",payment_type)

    # if payment_type=="Recurring Payment":
    req_token_boolean = True
    recurring_init_boolean = True
    # else:
    #     req_token_boolean = False
    #     recurring_init_boolean = False
    # frappe.log_error("req_token_boolean",req_token_boolean)
    # frappe.log_error("recurring_init_boolean",recurring_init_boolean)

    # Payment redirect url
    payment_redirect_url = authentication_of_payment_request(
        id_generated_value, 
        order_amount_hash, 
        order_currency_hash, 
        order_description_hash, 
        whatsapp_contact_id, 
        first_name, 
        last_name,
        generated_hashing_value, 
        req_token_boolean, 
        recurring_init_boolean,
        doc
    )

    return payment_redirect_url


def generating_the_order_no_for_payment(whatsapp_contact_id, site_name):
    last_four_digits = whatsapp_contact_id[-5:]
    random_suffix = ''.join(random.choices('0123456789', k=15))
    formatted_site_name = (site_name.lower()).replace(" ", "-")
    sales_invoice_field_values = f"Trie-{formatted_site_name}-{last_four_digits}-{random_suffix}"
    # frappe.log_error("generating_the_order_no_for_payment:",sales_invoice_field_values)
    return sales_invoice_field_values


def generating_the_hash_for_payment_authentication(order_number_hash, order_amount_hash, order_currency_hash, order_description_hash, merchant_pass_hash):
    order_amount_hash = str(order_amount_hash)
    data = (order_number_hash + order_amount_hash + order_currency_hash + order_description_hash + merchant_pass_hash).upper()
    md5_hash = hashlib.md5(data.encode()).hexdigest()
    sha1_hash = hashlib.sha1(md5_hash.encode()).hexdigest()
    # frappe.log_error("generating_the_hash_for_payment_authentication:",sha1_hash)
    return sha1_hash


def authentication_of_payment_request(order_number_hash, order_amount_hash, order_currency_hash, order_description_hash, whatsapp_contact_id, first_name, last_name, generated_hashing_value, req_token_boolean, recurring_init_boolean, doc):
    site_config = frappe.get_site_config()
    global_totalpay_url = site_config.get("global_totalpay_url")
    external_subscription_url = site_config.get("external_subscription_url")
    merchant_key = site_config.get("merchant_key")

    cleaned_full_name = None
    order_amount_hash = str(order_amount_hash)
    full_name = f"{first_name} {last_name}"
    if re.search(r'[^\w\s]', full_name):
        cleaned_full_name = re.sub(r'[^\w\s]', ' ', full_name)
    else:
        cleaned_full_name = full_name

    methods = ["card"] if recurring_init_boolean else ["card", "applepay"] 
    # frappe.log_error("Payment Methods", f"Methods: {methods}, Recurring: {recurring_init_boolean}, Type: {payment_type}")

    url = f"{global_totalpay_url}/api/v1/session"
    payload = json.dumps({
      "merchant_key": f"{merchant_key}",
      "operation": "purchase",
      "methods": methods,
      "customer": {
        "birth_date": "2000-01-01",
      },
      "order": {
        "number": order_number_hash,
        "amount": order_amount_hash,
        "currency": order_currency_hash,
        "description": order_description_hash
      },
      "cancel_url": f"{external_subscription_url}?payment_status=failed",
      "success_url": f"{external_subscription_url}?payment_status=success",
      "customer": {
        "name": f"{cleaned_full_name}",
        "email": f"{whatsapp_contact_id}@trie.com"
      },
      "billing_address": {
        "phone": whatsapp_contact_id,
        "country": "AE",
        "state": "Dubai",
        "city": "Al Quoz",
        "district": "Al Quoz",
        "address": doc.site_name,
        "house_number": "AKG 007",
        "zip": "122002"
      },
      "req_token": req_token_boolean,
      "recurring_init": recurring_init_boolean,
      "hash": generated_hashing_value,
      "session_expiry" : 719
    })
    headers = {
      'Content-Type': 'application/json'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    json_response = frappe.utils.data.json.loads(response.text)
    return json_response


def creating_new_customer_vehicle_order(id_generated_value, whatsapp_id):
    getting_whatsapp_customer_doc = frappe.get_doc("WhatsApp Customer Details", whatsapp_id)

    if getting_whatsapp_customer_doc:
        new_doc = frappe.new_doc("Customer Vehicle Order")
        new_doc.order_id = id_generated_value
        new_doc.site_location = getting_whatsapp_customer_doc.site_name
        new_doc.car_registration_number = getting_whatsapp_customer_doc.car_registration_number
        new_doc.car_type = getting_whatsapp_customer_doc.car_type
        new_doc.car_brand_and_model = getting_whatsapp_customer_doc.car_brand_and_model
        new_doc.car_color = getting_whatsapp_customer_doc.car_color
        
        # Handle custom_car_brand_and_model condition
        if getting_whatsapp_customer_doc.car_brand_and_model == '':
            new_doc.car_brand_and_model = getting_whatsapp_customer_doc.car_brand_and_model
            new_doc.car_brand = getting_whatsapp_customer_doc.custom_car_brand
            new_doc.car_model = getting_whatsapp_customer_doc.custom_car_model
            new_doc.car_type = getting_whatsapp_customer_doc.car_type
        else:
            new_doc.car_brand_and_model = getting_whatsapp_customer_doc.car_brand_and_model
            car_brand_and_model_doc = frappe.get_doc("Car Brand And Model", getting_whatsapp_customer_doc.car_brand_and_model)
            new_doc.car_type = car_brand_and_model_doc    

        new_doc.save(ignore_permissions=True)
    else:
        pass


# -------------------------------------------------------------------------------------------------       PAYMENT STATUS UPDATION


def process_successful_payment(sales_invoice_doc, hash_value, webhook_values):
    """Process the payment when the webhook response is successful."""
    if sales_invoice_doc.status == "Paid":
        frappe.log_error(f"Duplicate webhook for already-paid invoice {sales_invoice_doc.name}. Skipping.", "Duplicate Webhook Skipped")
        return

    try:
        # Update Sales Invoice
        update_sales_invoice_payment_status(
            sales_invoice_doc, hash_value, webhook_values.get("custom_order_amount"), webhook_values.get("custom_id"), webhook_values.get("custom_payment_time"), webhook_values.get("custom_approval_code")
        )
        # Fetch Customer Document
        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
        subscription_doc_name = creating_subscription_against_user(
            sales_invoice_doc, customer_doc, webhook_values
        )
        update_customer_subscription(customer_doc, subscription_doc_name, hash_value)
        if subscription_doc_name:

            # updating sales invoice with subscription details
            updated_sales_invoice_doc, to_date = update_sales_invoice_with_subscription(sales_invoice_doc, subscription_doc_name)

            # creating payment scheduler for the subscription
            schedule_id = create_payment_scheduler(subscription_doc_name, webhook_values, hash_value)
            try:
                from .subscription_actions import update_scheduler_date_and_amount
                to_date = updated_sales_invoice_doc.to_date if updated_sales_invoice_doc.to_date else to_date
                if schedule_id:
                    update_scheduler_date_and_amount(schedule_id, to_date, updated_sales_invoice_doc.rounded_total or updated_sales_invoice_doc.grand_total)
                else:
                    frappe.log_error(f"Scheduler creation returned None for {subscription_doc_name} — UPDATE_DATE skipped", "Scheduler Creation Failed")
            except Exception as e:
                frappe.log_error("Error updating subscription scheduler", e)
    except Exception as e:
        frappe.log_error(f"Error processing successful payment for Sales Invoice", e)


def process_failed_payment(sales_invoice_doc, hash_value, amount, failed_reason):
    """Process the payment when the webhook response indicates failure.""" 
    try:
        counting_payment_webhook_log = frappe.get_all("Payment Webhook Log", filters={"custom_order_number": sales_invoice_doc.custom_order_id, "custom_status": "fail"})
        if len(counting_payment_webhook_log) == 5:
            sales_invoice_doc.custom_payment_hash_value = hash_value
            sales_invoice_doc.is_paid = 0
            sales_invoice_doc.is_pos = 0
            sales_invoice_doc.status = "Online Payment Failed"
            sales_invoice_doc.save(ignore_permissions=True)

            # change lead status and whatsapp customer status to payment failed
            try:
                if counting_payment_webhook_log:
                    update_lead_status_on_payment_actions(sales_invoice_doc, "Payment Failed")
                    update_whatsapp_customer_details_status(sales_invoice_doc, "Payment Failed")
            except Exception as e:
                frappe.log_error("Error occured on updating Payment Failed lead status", e)
        
            # Sending payment failure message to the user through SMS
            customer = frappe.get_value("Sales Invoice", sales_invoice_doc.name, ["customer"])
            whatsapp_id = frappe.get_value("Customer", customer, ["custom_mobile_number"])
            payment_failure(whatsapp_id, sales_invoice_doc, failed_reason)

    except Exception as e:
        frappe.log_error(f"Error processing failed payment for Sales Invoice", e)


def update_sales_invoice_payment_status(sales_invoice_doc_info, hash_value, amount, id, payment_time=None, approval_code=None):
    """Helper function to update sales invoice payment status."""
    try:
        log_operational("update_sales_invoice_payment_status","Updating Sales Invoice payment status with hash value, amount and payment id")
        sales_invoice_doc = sales_invoice_doc_info.reload()
        sales_invoice_doc.custom_payment_hash_value = hash_value
        sales_invoice_doc.custom_payment_id = id
        sales_invoice_doc.custom_actual_payment_date = getdate(payment_time) if payment_time else None
        sales_invoice_doc.custom_auth_code = approval_code 
        sales_invoice_doc.is_paid = 1
        sales_invoice_doc.is_pos = 1
        sales_invoice_doc.status = "Paid"
        
        payment_item = {
            "doctype": "Sales Invoice Payment",
            "mode_of_payment": "Recurring Payment",
            "amount": sales_invoice_doc.rounded_total or sales_invoice_doc.grand_total
        }

        # sales_tax_template = frappe.db.get_value('Sales Taxes and Charges Template', {'is_default': "1"}, 'name')
        # sales_invoice_doc.taxes_and_charges=sales_tax_template
        # taxes = get_taxes_and_charges("Sales Taxes and Charges Template", sales_invoice_doc.taxes_and_charges)
        # for tax in taxes:
        #     sales_invoice_doc.append("taxes", tax)

        sales_invoice_doc.append("payments", payment_item)
        sales_invoice_doc.save(ignore_permissions=True)
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Error updating saving Sales Invoice {sales_invoice_doc.name}: {str(e)}")


def update_customer_subscription(customer_doc, subscription_name, hash_value):
    """Update customer document with subscription details."""
    try:
        customer_doc = customer_doc.reload()
        for subscription in customer_doc.custom_subscription_list:
            if not subscription.order_id:
                subscription.subscription = subscription_name
                subscription.order_id = hash_value
                subscription.payment_status = hash_value
        customer_doc.save(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Error updating Customer {customer_doc.name} with subscription: {str(e)}")



@frappe.whitelist(allow_guest=True)
def update_sales_invoice_with_subscription(sales_invoice_doc_info, subscription_name):
    try:
        from trie_crm.invoice_and_service_job import get_billing_interval_details, process_subscription_after_invoice, has_sufficient_time, find_next_service_day, update_vehicle_services_from_plan
        from trie_crm.triecrm_functions import cost_per_wash,get_wash_dates,get_wash_days_frequency

        log_operational(f"sales_invoice: {sales_invoice_doc_info.name}, subscription: {subscription_name}","Starting update_sales_invoice_with_subscription")

        has_time = True

        # Extract subscription name if passed as a list of dict
        if isinstance(subscription_name, list) and len(subscription_name) > 0:
            if isinstance(subscription_name[0], dict) and 'name' in subscription_name[0]:
                subscription_name = subscription_name[0]['name']

        # Fetch and validate documents
        sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice_doc_info.name)
        subscription_doc = frappe.get_doc("Subscription", subscription_name)

        log_operational(f"Documents fetched : {{'invoice_status': {sales_invoice_doc.docstatus}, 'subscription_status': {subscription_doc.custom_subscription_status}}}", "Documents fetched")

        current_date = datetime.strptime(frappe.utils.today(), "%Y-%m-%d").date()

        # Update posting date and subscription
        posting_date = getdate(frappe.utils.today())
        sales_invoice_doc.posting_date = posting_date
        sales_invoice_doc.subscription = subscription_name
        if subscription_doc.custom_reference_id and frappe.db.exists("User", subscription_doc.custom_reference_id):
            sales_invoice_doc.custom_reference_id = subscription_doc.custom_reference_id

        # Calculate dates
        try:
            latest_to_date = getdate(sales_invoice_doc.to_date) if sales_invoice_doc.to_date else posting_date
        except Exception as e:
            frappe.log_error("Error getting latest_to_date", str(e))
            latest_to_date = posting_date

        has_paid_current_period = frappe.db.exists("Sales Invoice", {
            "subscription": subscription_name,
            "status": "Paid",
            "to_date": subscription_doc.current_invoice_end
        })

        if subscription_doc.current_invoice_end and posting_date <= getdate(subscription_doc.current_invoice_end) and has_paid_current_period:
            from_date = getdate(subscription_doc.current_invoice_end) + timedelta(days=1)
        else:
            from_date = getdate(subscription_doc.current_invoice_start)


        # Get billing interval and calculate to_date
        days_to_add = get_billing_interval_details(subscription_name, from_date)
        if days_to_add is not None:
            to_date = from_date + timedelta(days=days_to_add)
        else:
            to_date = subscription_doc.current_invoice_end - timedelta(days=1)

        # Check if current date equals from_date and adjust if needed
        if current_date == from_date:
            current_day_name = current_date.strftime("%A")
            is_wash_day = any(day.day == current_day_name for day in subscription_doc.custom_subscription_day_and_time)
            
            if is_wash_day:
                wash_time = next((day.time for day in subscription_doc.custom_subscription_day_and_time 
                                if day.day == current_day_name), None)
                
                has_time = has_sufficient_time(sales_invoice_doc_info.site_name, frappe.utils.nowtime(), wash_time)
                if not has_time:
                    next_wash_day = find_next_service_day(subscription_doc, current_date)
                    from_date = next_wash_day
                    
                    log_operational(description=f"Adjusted from_date due to insufficient time: original_date={current_date}, new_date={from_date}", title="From Date Adjustment")
        to_date = from_date + timedelta(days=days_to_add if days_to_add is not None else 29)

        # Set the calculated values in the document
        sales_invoice_doc.from_date = from_date
        sales_invoice_doc.to_date = to_date

        # Save before submit
        try:
            sales_invoice_doc.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error("Error saving sales invoice", str(e))
            raise
        
        sales_invoice_doc.reload()
        mode_of_payment = subscription_doc.custom_mode_of_payment or "Recurring Payment"
        final_amount = sales_invoice_doc.rounded_total or sales_invoice_doc.grand_total

        if sales_invoice_doc.payments:
            for payment in sales_invoice_doc.payments:
                payment.amount = final_amount
                payment.mode_of_payment = mode_of_payment
        else:
            sales_invoice_doc.append("payments", {
                "doctype": "Sales Invoice Payment",
                "mode_of_payment": mode_of_payment,
                "amount": final_amount
            })
        try:
            sales_invoice_doc.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error("Error saving updated payment amount after tax recalculation", str(e))
            raise


        # Submit the document
        try:
            if sales_invoice_doc.docstatus == 0:
                sales_invoice_doc.submit()
                frappe.db.commit()
        except Exception as e:
            frappe.log_error("Error submitting sales invoice", str(e))
            raise

        today = getdate(frappe.utils.today())
        existing_active_invoice = frappe.get_all(
            "Sales Invoice",
            filters={
                "subscription": subscription_name,
                "status": "Paid",
                "docstatus": 1,
                "name": ["!=", sales_invoice_doc.name],
                "from_date": ["<=", today],
                "to_date": [">=", today]
            },
            fields=["name"],
            limit=1
        )
        is_advance_payment = bool(existing_active_invoice)
        

        if not is_advance_payment:
            
            try:
                wash_days_with_count = get_wash_days_frequency(subscription_doc.custom_subscription_day_and_time)
                wash_dates = get_wash_dates(from_date, to_date, wash_days_with_count)
                subscription_doc.reload()
                subscription_doc.set("custom_vehicle_service", [])
                update_vehicle_services_from_plan(subscription_doc, wash_dates, from_date, to_date)
                deferred_total = sales_invoice_doc.net_total + sales_invoice_doc.discount_amount if sales_invoice_doc.discount_amount else sales_invoice_doc.net_total
                cost_per_wash(subscription_doc.name, deferred_total, wash_dates)
            except Exception as e:
                frappe.log_error("Error updating vehicle services", str(e))
                

        # Update subscription status and dates
        try:
            subscription_doc.reload()
            subscription_doc.custom_subscription_status = "Active"

            if not is_advance_payment:
                # Current period — update live dates
                subscription_doc.current_invoice_start = from_date
                subscription_doc.current_invoice_end = to_date
            else:
                
                subscription_doc.custom_next_start_date = from_date
                log_operational(
                    f"Advance payment: today ({today}) is covered by invoice "
                    f"{existing_active_invoice[0].name}. "
                    f"Storing next start={from_date}. Period NOT changed.",
                    "Advance Payment Guard"
                )

            subscription_doc.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error("Error updating subscription", str(e))
            raise

        # Process subscription after invoice if needed
        if current_date == from_date and has_time:
            try:
                process_subscription_after_invoice(sales_invoice_doc.name)
                log_operational("Processed subscription after invoice", f"Subscription processed for Sales Invoice {sales_invoice_doc.name} with subscription {subscription_name}")
            except Exception as e:
                frappe.log_error("Error processing subscription after invoice", str(e))

        # Send WhatsApp Notifications
        try:
            whatsapp_id = subscription_doc.custom_whatsapp_number
            if not whatsapp_id:
                frappe.log_error("WhatsApp notification skipped", "No WhatsApp number found")
                return sales_invoice_doc, to_date

            apps = frappe.get_single("Installed Applications").installed_applications
            app_array = [app.app_name for app in apps if app.app_name == "trie_whatsapp"]
            
            if app_array:
                from trie_whatsapp.whatsapp_templates import successfully_created_subscription
                from trie_whatsapp.trie_external_form_functions import sending_sales_invoice_receipt
                successfully_created_subscription(whatsapp_id)
                sending_sales_invoice_receipt(subscription_doc, events=None)
            
            payment_success(whatsapp_id, sales_invoice_doc, subscription_name)
            subscription_message(whatsapp_id)
            
        except Exception as e:
            frappe.log_error("WhatsApp notification failed", str(e))
            
        return sales_invoice_doc, to_date
    except Exception as e:
        frappe.log_error(f"Error in update_sales_invoice_with_subscription for {sales_invoice_doc_info.name}", {
            "error": str(e),
            "traceback": frappe.get_traceback()
        })
        raise

def create_payment_scheduler(subscription_name, webhook_values, hash_value):
    """Create a payment scheduler for the subscription."""
    subscription = frappe.get_doc("Subscription", subscription_name)
    try:
        subscription.lock(timeout=15)
    except frappe.DocumentLockedError:
        frappe.log_error(
            f"create_payment_scheduler: could not lock {subscription_name} within 15s, "
            f"another call is already creating a scheduler for it. Aborting.",
            "Duplicate Scheduler Creation Blocked"
        )
        return subscription.custom_scheduler_id  # whatever is already there, don't create a second one
    try: 
        subscription.reload()
        if subscription.custom_scheduler_id:
            frappe.log_error(
                f"create_payment_scheduler called for {subscription.name} but "
                f"{subscription.custom_scheduler_id} is already tracked as active. Skipping.",
                "Duplicate Scheduler Creation Blocked"
            )
            return subscription.custom_scheduler_id
        subscription_plan = frappe.get_doc("Subscription Plan", subscription.plans[0].plan)
        
        site_config = frappe.get_site_config()
        merchant_pass_hash = site_config.get("merchant_password")
        log_operational("merchant_pass_hash", "Fetched merchant password for scheduler creation")
        scheduler_name = generating_scheduler_name(subscription.custom_whatsapp_number)
        
        hash_for_scheduler = generating_the_hash_for_scheduler(merchant_pass_hash)
        log_operational("hash_for_scheduler", hash_for_scheduler)
        order_amount_hash = webhook_values.get("custom_order_amount")

        try: 
            interval_unit = str(subscription_plan.billing_interval).lower() if str(subscription_plan.billing_interval).lower() else "day"
            interval_length = str(subscription_plan.billing_interval_count) if str(subscription_plan.billing_interval_count) else "28"
        except:
            interval_unit = "day"
            interval_length = "28"
            frappe.log_error(f"Error: Default day is set to 28 days for subscription {subscription_name}", scheduler_name)
            
        scheduler_values = {}
        schedule_id = None
        try:
            # frappe.log_error("interval_unit",interval_unit)
            # frappe.log_error("interval_length",interval_length)
            scheduler_values = creating_scheduler(hash_for_scheduler, scheduler_name, order_amount_hash, interval_unit, interval_length, webhook_values)
            # frappe.log_error("scheduler_values:",scheduler_values)

            if scheduler_values and scheduler_values != {}:
                json_response_data = scheduler_values.json()
                schedule_id = json_response_data["schedule_id"]
                
                # Reload subscription before updating to avoid timestamp mismatch
                subscription.reload()
                
        except Exception as e:
            frappe.log_error(f"Error on Creating Payment Scheduler for subscription {subscription_name}: {str(e)}")
        
        fields_to_update = {}
        if schedule_id:
            fields_to_update["custom_scheduler_id"] = schedule_id
            fields_to_update["custom_scheduler_name"] = scheduler_name
        if webhook_values.get("custom_recurring_init_transaction_id"):
            fields_to_update["custom_recurring_init_transaction_id"] = webhook_values.get("custom_recurring_init_transaction_id")
        if webhook_values.get("custom_recurring_token"):
            fields_to_update["custom_recurring_token"] = webhook_values.get("custom_recurring_token")

        if fields_to_update:
            frappe.db.set_value("Subscription", subscription_name, fields_to_update)
        frappe.db.commit()
        return schedule_id
    finally:
        subscription.unlock()

class DuplicateRenewalInvoice(Exception):
    """Raised when a Paid Sales Invoice already exists for the computed billing period."""
    pass


def handle_renewal_webhook_response(order_number, hash_value, webhook_values, paid_sales_invoice_names, payment_id, order_amount, draft_sales_invoice, mode_of_payment):
    """Handle the renewal webhook response."""
    try:
        from trie_crm.triecrm_functions import get_contract_end_date, get_wash_dates, get_wash_days_frequency
        # from .subscription_actions import cancel_payment_scheduler, updating_subscription_scheduler

        subscription_docs = []
        recurring_trans_id = webhook_values.get("custom_recurring_init_transaction_id")
        if recurring_trans_id:
            subscription_docs = frappe.get_all("Subscription",
                filters={"custom_recurring_init_transaction_id": recurring_trans_id},
                pluck="name")
        if not subscription_docs:
            recurring_token = webhook_values.get("custom_recurring_token")
            if recurring_token:
                subscription_docs = frappe.get_all("Subscription",
                    filters={"custom_recurring_token": recurring_token},
                    pluck="name")
        if not subscription_docs:
            subscription_docs = frappe.get_all("Subscription", filters={"custom_order_number": order_number}, pluck="name")

        if not subscription_docs:
            frappe.log_error(f"No Subscription found for order number {order_number}")
            return
        subscription_doc = frappe.get_doc("Subscription", subscription_docs[0])

        if subscription_doc.custom_subscription_status == "Cancelled":
            frappe.log_error(
                f"Renewal webhook received for already-cancelled subscription {subscription_doc.name} "
                f"(order_number={order_number}). Skipping - not creating a scheduler or invoice.",
                "Renewal Webhook Skipped: Subscription Cancelled"
            )
            return

        scheduler_id = subscription_doc.custom_scheduler_id
        current_date = frappe.utils.today()
        if not scheduler_id:
            frappe.log_error(f"No scheduler_id on {subscription_doc.name} at renewal. Attempting to create.", "Renewal: Missing Scheduler")
            create_payment_scheduler(subscription_doc.name, webhook_values, hash_value)
            subscription_doc.reload()
            scheduler_id = subscription_doc.custom_scheduler_id
        if not scheduler_id:
            frappe.log_error(f"Scheduler creation also failed for {subscription_doc.name}. Renewal cannot proceed.", "Renewal: Scheduler Creation Failed")
            return
        try:
            try:
                schedule_info_data = json.loads(scheduler_info(scheduler_id, generating_the_hash_id_for_subscription(scheduler_id)))
            except Exception as e:
                frappe.log_error(f"Could not fetch scheduler info for {scheduler_id}: {str(e)}", "Scheduler Info Fetch Failed")
                schedule_info_data = {}

            previous_order_number = frappe.get_value("Sales Invoice", {"subscription": subscription_doc.name, "status": "Paid"}, ["custom_order_id"])
            
            site = subscription_doc.custom_vehicle_information[0].site_name if subscription_doc.custom_vehicle_information else None
            sales_invoice_doc = frappe.get_doc("Sales Invoice", draft_sales_invoice.name) if draft_sales_invoice else frappe.new_doc("Sales Invoice")
            sales_invoice, subscription, to_date, mode_of_payment = create_sales_invoice_for_renewal(
                subscription_doc, schedule_info_data, webhook_values, paid_sales_invoice_names, hash_value, payment_id, site, draft_sales_invoice, sales_invoice_doc, mode_of_payment
            )

            # New contract-related logic
            if site:
                contract_end_date = get_contract_end_date(site)
                buffer_days = frappe.db.get_value('Branch', site, 'custom_site_contract_end_buffer') or 0
                
                # Calculate update_date based on conditions
                if contract_end_date > to_date:
                    wash_days_with_count = get_wash_days_frequency(subscription_doc.custom_subscription_day_and_time)
                    wash_dates = get_wash_dates(to_date, contract_end_date, wash_days_with_count)
                    
                    if wash_dates >= 1:
                        update_date = to_date
                    else:
                        update_date = frappe.utils.add_days(current_date, -1)
                else:
                    # If contract end date is equal to or before to_date
                    update_date = frappe.utils.add_days(current_date, -1)

                # frappe.log_error(f"Final update_date: {update_date}")

                if mode_of_payment == "Recurring Payment":
                    from trie_payments.subscription_actions import update_scheduler_date_and_amount
                    new_amount = sales_invoice_doc.rounded_total or sales_invoice_doc.grand_total

                    incoming_token = webhook_values.get("custom_recurring_token")
                    stored_token = subscription_doc.custom_recurring_token
                    is_new_card = incoming_token and stored_token and incoming_token != stored_token

                    if is_new_card:
                        try:
                            old_scheduler_id = subscription_doc.custom_scheduler_id
                            if old_scheduler_id:
                                result = update_scheduler_date_and_amount(old_scheduler_id, frappe.utils.add_days(today(), -1), 0)
                                if result == "failed":
                                    frappe.log_error(
                                        f"Failed to deactivate old scheduler {old_scheduler_id} for "
                                        f"{subscription_doc.name}. NOT proceeding to create a replacement "
                                        f"until this is resolved manually.",
                                        "Old Scheduler Deactivation Failed"
                                    )
                                    raise Exception(f"Could not deactivate old scheduler {old_scheduler_id}")
                                subscription_doc.custom_scheduler_id = None
                                subscription_doc.custom_scheduler_name = None
                        except Exception as e:
                            frappe.log_error(f"Failed to deactivate old scheduler for {subscription_doc.name}: {str(e)}", "Old Scheduler Deactivation Failed")
                            raise

                        try:
                            new_scheduler_id = create_payment_scheduler(subscription_doc.name, webhook_values, hash_value)
                            if new_scheduler_id:
                                update_scheduler_date_and_amount(new_scheduler_id, update_date, new_amount)
                        except Exception as e:
                            frappe.log_error(f"Failed to create new scheduler after card change for {subscription_doc.name}: {str(e)}", "New Scheduler Creation Failed")
                    else:
                        # Same card — just update existing scheduler
                        scheduler_id_to_update = subscription_doc.custom_scheduler_id
                        if not scheduler_id_to_update:
                            try:
                                scheduler_id_to_update = create_payment_scheduler(subscription_doc.name, webhook_values, hash_value)
                            except Exception as e:
                                frappe.log_error(f"Error creating scheduler for {subscription_doc.name}: {str(e)}", "Scheduler Creation Failed")

                        if scheduler_id_to_update:
                            try:
                                result = update_scheduler_date_and_amount(scheduler_id_to_update, update_date, new_amount)
                                if result == "failed":
                                    frappe.log_error(f"Scheduler update returned failed for {subscription_doc.name}. Date: {update_date}, Amount: {new_amount}", "Scheduler Update Warning")
                            except Exception as e:
                                frappe.log_error(f"Scheduler update exception for {subscription_doc.name}: {str(e)}", "Scheduler Update Failed")

            # Notification logic
            apps = frappe.get_single("Installed Applications").installed_applications
            if any(app.app_name in ["trie_whatsapp", "trie_crm"] for app in apps):
                try:
                    customer_name = frappe.get_value("Customer", subscription_doc.party, "customer_name")
                    service_plan = subscription_doc.plans[0].plan if subscription_doc.plans else None
                    vehicle_number = subscription_doc.custom_vehicle_information[0].registration_number if subscription_doc.custom_vehicle_information else None

                    from trie_whatsapp.whatsapp_templates import success_auto_renewal_webhook_response, send_customer_review_feedback_form
                    from trie_whatsapp.trie_external_form_functions import sending_sales_invoice_receipt

                    message_values = [subscription_doc.name, service_plan, vehicle_number, current_date, order_amount]
                    success_auto_renewal_webhook_response(subscription_doc.custom_whatsapp_number, message_values)

                    if subscription_doc.custom_scheduler_id and subscription_doc.custom_notifications_preference == 1 and subscription_doc.custom_subscription_status == "Active":
                        payment_renewal_success(subscription_doc.custom_whatsapp_number, customer_name, subscription_doc.name, service_plan, vehicle_number, current_date, order_amount)
                        sending_sales_invoice_receipt(subscription_doc, events=None)
                        send_customer_review_feedback_form(subscription_doc.custom_whatsapp_number)
                except Exception as e:
                    frappe.log_error(f"Error notifying subscription updates for {subscription_doc.name}: {str(e)}")

        except Exception as e:
            frappe.log_error(f"Error creating sales invoice or updating scheduler: {str(e)}")

    except Exception as e:
        frappe.log_error(f"Error handling renewal webhook response: {str(e)}")



def handle_failed_renewal_webhook_response(order_number, decline_reason, amount):
    try:
        # Check if there is a failed payment webhook log for today
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Count the number of failed payment webhook logs for today
        failed_logs_count = frappe.db.count(
            "Payment Webhook Log",
            filters={
                "custom_order_number": order_number,
                "custom_status": "fail",
                "creation": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]]
            }
        )
        
        # Send the message only if this is the first failed log for today
        if failed_logs_count == 1:
                
            subscription_docs = frappe.get_all("Subscription", filters={"custom_order_number": order_number}, pluck="name")
            if not subscription_docs:
                failed_log = frappe.get_all("Payment Webhook Log",
                    filters={"custom_order_number": order_number, "custom_status": "fail"},
                    fields=["custom_recurring_init_transaction_id", "custom_recurring_token"], limit=1)
                if failed_log:
                    if failed_log[0].get("custom_recurring_init_transaction_id"):
                        subscription_docs = frappe.get_all("Subscription",
                            filters={"custom_recurring_init_transaction_id": failed_log[0]["custom_recurring_init_transaction_id"]},
                            pluck="name")
                    if not subscription_docs and failed_log[0].get("custom_recurring_token"):
                        subscription_docs = frappe.get_all("Subscription",
                            filters={"custom_recurring_token": failed_log[0]["custom_recurring_token"]},
                            pluck="name")
            if not subscription_docs:
                log_operational(f"No Subscription found for order number {order_number}", "Failed Renewal Webhook")
                return
            
            subscription_doc = frappe.get_doc("Subscription", subscription_docs[0])
            customer_name = frappe.get_value(
                "Customer",
                filters={"custom_mobile_number": subscription_doc.custom_whatsapp_number},
                fieldname="customer_name")
            for plan_detail in subscription_doc.plans:
                service_plan = plan_detail.plan
            for vehicle_info in subscription_doc.custom_vehicle_information:
                vehicle_number = vehicle_info.registration_number
            apps = frappe.get_single("Installed Applications").installed_applications
            app_array = [app.app_name for app in apps if app.app_name in ["trie_whatsapp", "trie_crm"]]
            if app_array:
                # Move the import statement inside the function
                from trie_whatsapp.whatsapp_templates import failed_auto_renewal_webhook_response
                value = [subscription_doc.name, service_plan, vehicle_number, decline_reason]
                if subscription_doc.custom_scheduler_id and subscription_doc.custom_notifications_preference == 1 and subscription_doc.custom_subscription_status == "Active":
                    failed_auto_renewal_webhook_response(subscription_doc.custom_whatsapp_number, value)
                    # Sending payment renewal failure message to the user through SMS
                    payment_renewal_failure(subscription_doc.custom_whatsapp_number, subscription_doc.name, service_plan, vehicle_number, decline_reason)
                    return
                else:
                    pass
            return

    except Exception as e:
        frappe.log_error("Error on handling failed renewal webhook response", e)
        pass


# ----------------------------------------------------------------   Creating Subscription against the user


def creating_subscription_against_user(getting_sales_invoice_doc, getting_customer_doc, fetching_webhook_values):
    try:
        # Fetch existing subscriptions based on custom order number
        fetching_doc_values = frappe.get_all(
            "Subscription", 
            filters={"custom_order_number": fetching_webhook_values.get("custom_order_number")}
        )

        if fetching_doc_values:

            subscription_document = frappe.get_doc("Subscription", fetching_doc_values[0].name)
            log_operational(f"Found subscription document: {subscription_document.name}", "Creating Subscription Against User")
            for plans in subscription_document.plans:
                plan_name=plans.plan
                
            getting_subscription_plan = frappe.get_doc("Subscription Plan", plan_name)
            service_table = getting_subscription_plan.custom_service
            service_name = service_table[0].services if service_table and len(service_table) > 0 else None

            
            # Update subscription document fields
            subscription_document.update({
                "custom_mode_of_payment": "Recurring Payment",
                "custom_remaining_pause_days": 60,
                "custom_subscription_status": "Active",
                "custom_notifications_preference": 1,
                "custom_recurring_init_transaction_id": fetching_webhook_values.get("custom_recurring_init_transaction_id"),
                "custom_recurring_token": fetching_webhook_values.get("custom_recurring_token")
            })

            # Get plan package details
            plan_package_detail = getting_sales_invoice_doc.items[0].item_name
            item_doc = frappe.get_doc("Item", plan_package_detail)
            child_table_records = item_doc.get("custom_services_table", [])
            
            # Get all vehicles from the subscription
            vehicles = [vehicle.registration_number for vehicle in subscription_document.custom_vehicle_information]
            
            if not vehicles:
                frappe.throw("No vehicles found in subscription")
                
            # Calculate washes per vehicle
            for plan in child_table_records:
                if plan.qty <= 0:
                    continue
                    
                total_washes = plan.qty
                washes_per_vehicle = total_washes // len(vehicles)
                remaining_washes = total_washes % len(vehicles)
                
                # Distribute washes to vehicles
                for idx, vehicle_number in enumerate(vehicles):
                    extra_wash = 1 if idx < remaining_washes else 0
                    allocated_washes = washes_per_vehicle + extra_wash

                    if allocated_washes > 0:
                        # Check if the vehicle already has a row
                        existing_row = next(
                            (row for row in subscription_document.custom_vehicle_service
                            if row.vehicle_number == vehicle_number),
                            None
                        )

                        if existing_row:
                            # Update existing row
                            existing_row.qty += allocated_washes
                        else:
                            # Add a new row
                            subscription_document.append('custom_vehicle_service', {
                                'vehicle_number': vehicle_number,
                                'service': service_name,
                                'qty': allocated_washes,
                                'total_no_of_wash': allocated_washes,
                                'completed_wash': 0,
                                'missed_cancelled_wash': 0
                            })
            
            if fetching_webhook_values.get("custom_order_number"):
                subscription_document.custom_order_number = fetching_webhook_values.get("custom_order_number")

            # Save the subscription document
            subscription_document.save(ignore_permissions=True)

            # Reload the sales invoice document
            getting_sales_invoice_doc.reload()

            return subscription_document.name
        
        # Fetch the Sales Invoice document
        fetching_sales_invoice_doc = getting_sales_invoice_doc.reload()
        getting_subscription_plan = frappe.get_doc("Subscription Plan", fetching_sales_invoice_doc.items[0].item_name)
        customer_details = frappe.get_value ("WhatsApp Customer Details", getting_customer_doc.custom_mobile_number, ["email_id"])

        # Create a new subscription if no existing one is found
        if not fetching_doc_values:
            new_subscription = frappe.new_doc("Subscription")
            new_subscription.party_type = "Customer"
            new_subscription.company = "TriE"
            new_subscription.custom_whatsapp_number = getting_customer_doc.custom_mobile_number
            new_subscription.custom_order_number = fetching_webhook_values.get("custom_order_number")
            new_subscription.custom_recurring_init_transaction_id = fetching_webhook_values.get("custom_recurring_init_transaction_id")
            new_subscription.custom_recurring_token = fetching_webhook_values.get("custom_recurring_token")
            new_subscription.custom_remaining_pause_days = 60
            new_subscription.custom_subscription_channel = "WhatsApp"
            new_subscription.custom_mode_of_payment = "Recurring Payment"
            new_subscription.custom_subscription_status = "Active"
            new_subscription.custom_notifications_preference = 1
            new_subscription.party = getting_customer_doc.name
            new_subscription.status = "Active"
            new_subscription.custom_posting_date = frappe.utils.nowdate()
            if customer_details:
                new_subscription.custom_email = customer_details
            else:
                pass

            # Set the subscription dates
            new_subscription.start_date = frappe.utils.nowdate()
            end_date = dt.datetime.strptime(frappe.utils.nowdate(), "%Y-%m-%d") + dt.timedelta(days=1825)
            new_subscription.end_date = end_date.strftime("%Y-%m-%d")

            # Append plan information
            new_subscription.append('plans', {
                'plan': fetching_sales_invoice_doc.items[0].item_name,
                'qty': "1",
                'custom_package_service_per_week': getting_subscription_plan.custom_service_per_week,
                'custom_package_price': getting_subscription_plan.cost
            })
            
            # Fetch customer vehicle order information
            getting_customer_vehicle_order_info = frappe.get_doc("Customer Vehicle Order", fetching_webhook_values.get("custom_order_number"))
            
            # Append vehicle information based on whether a specific brand and model are provided
            if getting_customer_vehicle_order_info.car_brand_and_model == '':
                new_subscription.append('custom_vehicle_information', {
                    'site_name': getting_customer_vehicle_order_info.site_location,
                    'car_type': getting_customer_vehicle_order_info.car_type,
                    'registration_number': getting_customer_vehicle_order_info.car_registration_number,
                    'other_brand_and_model': "Other",
                    'car_color': getting_customer_vehicle_order_info.car_color,
                    'custom_input_car_brand': getting_customer_vehicle_order_info.car_brand,
                    'custom_input_car_model': getting_customer_vehicle_order_info.car_model
                })
            else:
                car_brand_and_model_doc = frappe.get_doc("Car Brand And Model", getting_customer_vehicle_order_info.car_brand_and_model)
                new_subscription.append('custom_vehicle_information', {
                    'site_name': getting_customer_vehicle_order_info.site_location,
                    'car_type': car_brand_and_model_doc.car_type,
                    'registration_number': getting_customer_vehicle_order_info.car_registration_number,
                    'brand_and_model': getting_customer_vehicle_order_info.car_brand_and_model,
                    'car_color': getting_customer_vehicle_order_info.car_color
                })
                
            site_name=getting_customer_vehicle_order_info.site_location

            # Fetch item details for the plan package
            plan_package_detail = fetching_sales_invoice_doc.items[0].item_name
            getting_quantity_from_item = frappe.get_doc("Item", plan_package_detail)
            child_table_records = getting_quantity_from_item.get("custom_services_table", [])
            
            # Append service details to the subscription
            for plan in child_table_records:
                getting_qty_value = plan.qty
                service_name=plan.services
            new_subscription.append('custom_vehicle_service', {
                'vehicle_number': getting_customer_vehicle_order_info.car_registration_number,
                'service': service_name,
                'qty': getting_qty_value
            })

            # Add subscription day and time rows based on service frequency
            services_per_week = getting_subscription_plan.custom_service_per_week
            for _ in range(int(services_per_week)):
                new_subscription.append("custom_subscription_day_and_time", {
                    "vehicle_number": getting_customer_vehicle_order_info.car_registration_number,
                    "day": "",
                    "time": ""
                })

            # Save the subscription document while ignoring permission and validation checks
            new_subscription.flags.ignore_validate = True
            new_subscription.save(ignore_permissions=True)
            
            try:
                updating_initial_car_customer(fetching_webhook_values, getting_customer_doc)
            except Exception as e:
                frappe.log_error("Updating new car detail creation error", e)

            return new_subscription.name  # Return the subscription ID

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Subscription Creation Error")


# ---------------------------------------------------------------   Custom Api to get subscription on passing order_id and hash


@frappe.whitelist()
def identifying_subscription_id_using_order_no(order_id, hash_value):
    fetching_sales_invoice_all = frappe.get_all("Sales Invoice", filters={"custom_order_id": order_id, "custom_payment_hash_value": hash_value})
    passing_sales_invoice = frappe.get_doc("Sales Invoice", fetching_sales_invoice_all)
    if passing_sales_invoice:
        fetching_all_subscription = frappe.get_all("Subscription", filters={"custom_order_number": order_id})
        if fetching_all_subscription:
            getting_subscription_doc = frappe.get_doc("Subscription", fetching_all_subscription[0].name)

            vehicle_details = [{
                "car_type": vehicle.car_type,
                "registration_number": vehicle.registration_number,
                "brand_and_model": vehicle.brand_and_model,
                "car_color": vehicle.car_color
            } for vehicle in getting_subscription_doc.custom_vehicle_information]

            # Getting value of customer from subscription
            getting_customer_name_value = frappe.get_value("Customer", getting_subscription_doc.party, ["customer_name"])

            # Access the plan package detail
            plan_name = getting_subscription_doc.get("plans", [])
            for plan in plan_name:
                getting_plan_value = plan.plan
                getting_package_service_per_week = plan.custom_package_service_per_week
            total_number_of_washes = getting_subscription_doc.get("custom_vehicle_service", [])
            for plan in total_number_of_washes:
                getting_total_number_of_washes_value = plan.qty


            response = {
                "subscription_id": getting_subscription_doc.name,
                "customer_name": getting_customer_name_value,
                "site_name": getting_subscription_doc.custom_vehicle_information[0].site_name if getting_subscription_doc.custom_vehicle_information else "",
                "vehicle_details": vehicle_details,
                "package_service_per_week": str(getting_package_service_per_week),
                "total_number_of_washes": getting_total_number_of_washes_value,
                "package_name": getting_plan_value,
                "sales_invoice_id": passing_sales_invoice.name
            }

            return response
        else:
            return {"error": "Subscription Not Found"}
    else:
        return {"error": "Subscription Not Found"}


def updating_initial_car_customer(fetching_webhook_values, getting_customer_doc):
    getting_customer_vehicle_order_info = frappe.get_doc("Customer Vehicle Order", fetching_webhook_values.get("custom_order_number"))

    # Get the existing customer document
    # customer_doc = frappe.get_doc("Customer", getting_customer_doc.name)
    customer_doc = getting_customer_doc.reload()
    
    # Determine the brand and model values based on the car brand and model
    brand_and_model = f"{getting_customer_vehicle_order_info.car_brand} {getting_customer_vehicle_order_info.car_model}" if getting_customer_vehicle_order_info.car_brand_and_model == "" else getting_customer_vehicle_order_info.car_brand_and_model
    
    # Check if the vehicle information already exists
    existing_vehicle = next((vehicle for vehicle in customer_doc.custom_vehicle_information 
                             if vehicle.registration_number == getting_customer_vehicle_order_info.car_registration_number), None)

    if existing_vehicle:
        return
    else:
        # Append new vehicle information if it doesn't exist
        customer_doc.append('custom_vehicle_information', {
            'site_name': getting_customer_vehicle_order_info.site_location,
            'car_type': getting_customer_vehicle_order_info.car_type,
            'registration_number': getting_customer_vehicle_order_info.car_registration_number,
            'car_color': getting_customer_vehicle_order_info.car_color,
            'brand_and_model': brand_and_model if getting_customer_vehicle_order_info.car_brand_and_model != "" else None,
            'other_brand_and_model': brand_and_model if getting_customer_vehicle_order_info.car_brand_and_model == "" else None
        })

    # Save the updated customer document
    customer_doc.save(ignore_permissions=True)




# -----------------------------------------------------------------------------------  Updating subscription details,   Also updating subscription on completion of finalize form

@frappe.whitelist()
def updating_subscription_details(subscription_id, building_number, flat_number, parking_level, parking_lot, wash_days, wash_time, custom_wash_reminder_preference,remarks):
    # frappe.set_user("Administrator")

    # Fetching the subscription document
    subscription_doc = frappe.get_doc("Subscription", subscription_id)
    subscription_doc.custom_wash_reminder_preference = custom_wash_reminder_preference

    #saving subscription remarks
    subscription_doc.custom_remarks=remarks

    # Initialize the response dictionary
    response = {
        "vehicle_details_and_location_details": [],
        "wash_day_details": [],
        "number_of_days": subscription_doc.number_of_days
    }

    # Updating vehicle details with bay and zone information
    if subscription_doc.custom_vehicle_information:
        for vehicle in subscription_doc.custom_vehicle_information:
            if not vehicle.flat_number and vehicle.registration_number:
                vehicle.building_number = building_number
                vehicle.flat_number = flat_number
                vehicle.parking_level_number = parking_level
                vehicle.parking_lot_number = parking_lot

    # Split wash_days into a list if it's a string
    if isinstance(wash_days, str):
        wash_days = [day.strip() for day in wash_days.split(",")]

    subscription_doc.set("custom_subscription_day_and_time", [])        

    # Updating wash day and time details
    for wash_day in wash_days:
        subscription_doc.append("custom_subscription_day_and_time", {
            "vehicle_number": vehicle.registration_number,
            "day": wash_day,
            "time": wash_time
        })

    response["wash_day_details"].append({
        "wash_day": wash_days,
        "time": wash_time
    })

    try:
        # Set flags to ignore validation and mandatory field checks
        subscription_doc.flags.ignore_validate = True
        subscription_doc.save(ignore_permissions=True)

        # Find the bay and zone after the document is saved
        try:
            
            # Fetch all bays
            all_bays = frappe.get_all("Bay", fields=["name", "zone"])
            bay_name = None
            zone_name = None
            for bay in all_bays:
                building_numbers = frappe.get_all("Building Detail", 
                                                  filters={"parent": bay.name},
                                                  fields=["building_number"])
                parking_levels = frappe.get_all("Parking Level Detail", 
                                                filters={"parent": bay.name},
                                                fields=["parking_level"])

                if any(b.building_number == building_number for b in building_numbers) and \
                   any(p.parking_level == parking_level for p in parking_levels):
                    bay_name = bay.name
                    zone_name = bay.zone
                    break

            # Updating vehicle details with bay and zone information
            if subscription_doc.custom_vehicle_information:
                for vehicle in subscription_doc.custom_vehicle_information:
                    if vehicle.flat_number and vehicle.registration_number:
                        if bay_name:
                            vehicle.bay_name = bay_name
                            vehicle.zone_name = zone_name
                        else:
                            pass

            # Set flags to ignore validation and mandatory field checks
            # subscription_doc.flags.ignore_validate = True
            subscription_doc.save(ignore_permissions=True)

        except Exception as inner_error:
            frappe.log_error("Error updating vehicle details", inner_error)
            pass

    except Exception as e:
        frappe.log_error("Error saving subscription document", e)
        pass

    # Change lead status and whatsapp customer status to subscribed
    try:
        getting_sales_invoice_doc = frappe.get_all("Sales Invoice", filters = {"subscription": subscription_doc.name})
        update_lead_status_on_payment_actions(getting_sales_invoice_doc[0], "Subscribed")
        update_whatsapp_customer_details_status(getting_sales_invoice_doc[0], "Subscribed")
    except Exception as e:
        frappe.log_error("Error occured on updating Subscribed lead status", e)

    # If there's a WhatsApp number, handle related updates on the Customer doctype
    if subscription_doc.custom_whatsapp_number:
        whatsapp_no = subscription_doc.custom_whatsapp_number
        whatsapp_contact_id = whatsapp_no if whatsapp_no.startswith('+') else '+' + whatsapp_no
    
        # Iterate over the vehicle information in the subscription document
        for vehicle_info in subscription_doc.custom_vehicle_information:
            registration_number_value = vehicle_info.registration_number
    
            try:
                if registration_number_value:
                    # Fetch customer based on WhatsApp number
                    customer_list = frappe.get_all("Customer", filters={"custom_mobile_number": whatsapp_no})
                    
                    if customer_list:
                        customer_doc = frappe.get_doc("Customer", customer_list[0].name)
    
                        # Update customer vehicle details where registration number matches
                        for vehicle_inform in customer_doc.custom_vehicle_information:
                            if vehicle_inform.registration_number == registration_number_value:
    
                                # Update vehicle details directly
                                vehicle_inform.flat_number = vehicle_info.flat_number
                                vehicle_inform.building_number = vehicle_info.building_number
                                vehicle_inform.parking_lot_number = vehicle_info.parking_lot_number
                                vehicle_inform.parking_level_number = vehicle_info.parking_level_number
                                vehicle_inform.zone_name = vehicle_info.zone_name
                                vehicle_inform.bay_name = vehicle_info.bay_name
        
                        customer_doc.save(ignore_permissions=True)
                        frappe.db.commit()
    
            except Exception as e:
                frappe.log_error("Error on updating customer vehicle details", e)
                pass

    # calling the whatsapp sales invoice sending function after updating the location of the vehicle
    try:
        apps = frappe.get_single("Installed Applications").installed_applications
        app_array = [app.app_name for app in apps if app.app_name in ["trie_whatsapp", "trie_crm"]]
        if app_array:
            # Move the import statement inside the function
            from trie_whatsapp.trie_external_form_functions import sending_sales_invoice_receipt
            sending_sales_invoice_receipt(subscription_doc, None)            

            # getting_sales_invoice_doc = frappe.get_all("Sales Invoice", filters = {"subscription": subscription_doc.name})
            # fetching_sales_invoice_doc = frappe.get_doc("Sales Invoice", getting_sales_invoice_doc)

            # calling service job function after updating the location of the vehicle
            # from trie_crm.invoice_and_service_job import process_subscription_after_invoice
            # process_subscription_after_invoice(fetching_sales_invoice_doc.name)

    except Exception as e:
        frappe.log_error("Error on sending sales invoice receipt", e)
        pass

    return response


# ----------------------------------------------------------------   Functions for Scheduler


def generating_the_hash_for_scheduler(merchant_pass_hash):
    # Reverse the merchant_pass_hash and convert it to uppercase
    reversed_upper_pass = merchant_pass_hash[::-1].upper()
    # Calculate the MD5 hash of the resulting string
    md5_hash = hashlib.md5(reversed_upper_pass.encode()).hexdigest()
    return md5_hash


def generating_scheduler_name(whatsapp_id):
    random_suffix = ''.join(random.choices('0123456789', k=5))
    order_id = f"Trie-{whatsapp_id}-{random_suffix}"
    return order_id


def creating_scheduler(hash_for_scheduler, scheduler_name, order_amount_hash, interval_unit, interval_length, webhook_values):
    # Extracting the JSON string from the tuples
    json_string = webhook_values.get("json_response")
    if json_string:
        parsed_json = json.loads(json_string)
        recurring_trans_id = parsed_json.get('recurring_init_trans_id')
        recurring_token_id = parsed_json.get('recurring_token')
    else:
        recurring_trans_id = webhook_values.get("custom_recurring_init_transaction_id")
        recurring_token_id = webhook_values.get("custom_recurring_token")
    site_config = frappe.get_site_config()
    scheduler_url = site_config.get("scheduler_url")
    merchant_id = site_config.get("merchant_id")
    merchant_key = site_config.get("merchant_key")

    url = f"{scheduler_url}/post"
    payload = {
        'action': 'CREATE_SCHEDULE',
        'merchant_id': f'{merchant_id}',
        'client_key': f'{merchant_key}',
        'name': f'{scheduler_name}',
        'interval_unit': f'{interval_unit}',
        'interval_length': f'{interval_length}',
        'amount': f'{order_amount_hash}',
        'hash': f'{hash_for_scheduler}',
        'payments_count': '99',
        'recurring_init_trans_id': f'{recurring_trans_id}',
        'recurring_token': f'{recurring_token_id}',
        'day_of_month': '1'
    }
    files=[
    ]
    headers = {}
    response = requests.post(url, headers=headers, data=payload, files=files)
    log_operational("response",response)
    return response


def scheduler_info(schedule_id, generated_hash_id):
    site_config = frappe.get_site_config()
    scheduler_url = site_config.get("scheduler_url")
    merchant_id = site_config.get("merchant_id")
    merchant_key = site_config.get("merchant_key")

    url = f"{scheduler_url}/post"
    payload = {
        'action': 'SCHEDULE_INFO',
        'client_key': f'{merchant_key}',
        'schedule_id': schedule_id,
        'hash': generated_hash_id,
        'merchant_id': f'{merchant_id}'
    }
    files=[
    ]
    headers = {}
    response = requests.request("POST", url, headers=headers, data=payload, files=files)
    return response.text


# ---------------------------------------------------------------   Supporting and Needed Syntaxes


def find_bay_by_parking_level(parking_level_value):
    # Fetch all Bay documents
    bay_docs = frappe.get_all('Bay', fields=['name', 'bay_name'])
    # Iterate through each Bay document
    for bay_doc in bay_docs:
        # Load the full document to access child table fields
        bay = frappe.get_doc('Bay', bay_doc['name'])
        # Check each parking_level_value in the Bay document
        for parking_level in bay.parking_level_number:
            if parking_level.parking_level == parking_level_value:
                # If found, return the bay_name and name
                return {
                    "bay_name": bay.bay_name,
                    "name": bay.name
                }
    # Return None if no matching parking level is found
    return None

@frappe.whitelist(allow_guest= True)
def generating_the_hash_id_for_subscription(schedule_id):
    if schedule_id:
        site_config = frappe.get_site_config()
        merchant_pass_hash = site_config.get("merchant_password")
        # Concatenate the schedule_id (order_number_hash in this context) and merchant_pass_hash
        concatenated_string = schedule_id + merchant_pass_hash
        # Reverse the concatenated string and convert it to uppercase
        reversed_upper_string = concatenated_string[::-1].upper()
        # Calculate the MD5 hash of the resulting string
        md5_hash = hashlib.md5(reversed_upper_string.encode()).hexdigest()
        return md5_hash




def create_sales_invoice_for_renewal(subscription_doc, schedule_info_data, webhook_values, last_invoice, hash_value, payment_id, site, draft_invoice, invoice_doc, mode_of_payment):
    """Create renewal sales invoice with service table update"""
    try:
        from trie_crm.triecrm_functions import cost_per_wash,get_wash_dates, calculate_billing_dates, get_contract_end_date, calculate_invoice_amount,get_wash_days_frequency,get_income_account
        from trie_crm.invoice_and_service_job import update_vehicle_services, get_billing_interval_details,has_sufficient_time,find_next_service_day,process_subscription_after_invoice
        
        current_date = getdate(frappe.utils.today())
        contract_end_date = get_contract_end_date(site)
        subscription_plan = frappe.get_doc("Subscription Plan", subscription_doc.plans[0].plan)

        existing_paid_invoices = frappe.get_all("Sales Invoice",
                filters={"subscription": subscription_doc.name, "status": "Paid"},
                fields=["name", "from_date", "to_date"],
                order_by="creation DESC"
        )
        # Calculate from_date
        if existing_paid_invoices:
            last_to_date = getdate(existing_paid_invoices[0].to_date)
            if last_to_date >= current_date:
                from_date = last_to_date + timedelta(days=1)
            else:
                from_date = current_date
        else:
            # Check if the subscription is upgraded/downgraded
            # If yes, calculate from_date based on parent subscrptions's last invoice to_date 
            using_upgrade_from_date = False

            upgrade_actions = frappe.get_all(
                "Subscription Action",
                filters={"new_subscription_id": subscription_doc.name, "docstatus": 1},
                fields=["subscription_id"]
            )
            log_operational(upgrade_actions,"Upgrade actions fetched")

            if upgrade_actions:
                parent_sub_id = upgrade_actions[0].get("subscription_id")
                if parent_sub_id:
                    last_inv = frappe.get_all(
                        "Sales Invoice",
                        filters={"subscription": parent_sub_id, "docstatus": 1},
                        fields=["name", "to_date"],
                        order_by="creation DESC"
                    )

                    if last_inv and last_inv[0].get("to_date"):
                        from_date = getdate(last_inv[0].get("to_date")) + timedelta(days=1)

                        frappe.log_error("Upgrade detected. Using parent's last invoice to_date + 1", {
                            "parent_subscription": parent_sub_id,
                            "parent_invoice": last_inv[0].get("name"),
                            "calculated_from_date": from_date
                        })

                        using_upgrade_from_date = True
                    else:
                        using_upgrade_from_date = False
                else:
                    using_upgrade_from_date = False
            else:
                using_upgrade_from_date = False

            if not using_upgrade_from_date:
                from_date = current_date
        
        duplicate_invoice = next(
            (inv for inv in existing_paid_invoices if getdate(inv.from_date) == from_date),
            None
        )
        if duplicate_invoice:
            frappe.log_error(
                f"Duplicate renewal webhook for subscription {subscription_doc.name}, "
                f"period starting {from_date}. Invoice {duplicate_invoice.name} already exists. Skipping.",
                "Duplicate Renewal Webhook Skipped"
            )
            raise DuplicateRenewalInvoice(duplicate_invoice.name)

        if from_date > contract_end_date:
            frappe.throw(f"Cannot generate invoice as the contract ended on {contract_end_date}")
        has_time = True

        if current_date == from_date:
            current_day_name = current_date.strftime("%A")
            is_wash_day = any(day.day == current_day_name for day in subscription_doc.custom_subscription_day_and_time)
            
            if is_wash_day:
                wash_time = next((day.time for day in subscription_doc.custom_subscription_day_and_time 
                                if day.day == current_day_name), None)
                has_time = has_sufficient_time(site, frappe.utils.nowtime(), wash_time)
                if not has_time:
                    from_date = find_next_service_day(subscription_doc, current_date)

        if from_date > contract_end_date:
            frappe.throw(f"Cannot generate invoice as the contract ended on {contract_end_date}")

        billing_days = get_billing_interval_details(subscription_doc.name, from_date)
        if not billing_days:
            frappe.throw("Could not determine billing interval")
        
        to_date = from_date + timedelta(days=billing_days)
        needs_special_pricing = False
        
        if to_date > contract_end_date:
            to_date = contract_end_date
            needs_special_pricing = True

        # Clear existing items and payments if any
        invoice_doc.items = []
        invoice_doc.payments = []

        cost_center = frappe.db.get_value('Cost Center', {'custom_branch': site}, 'name')
        renewal_payment_time = webhook_values.custom_payment_time
        renewal_reference_id = subscription_doc.custom_reference_id

        # Setup basic invoice fields
        invoice_doc.update({
            "customer": subscription_doc.party,
            "subscription": subscription_doc.name,
            "posting_date": current_date,
            "custom_order_id": webhook_values.custom_order_number,
            "custom_payment_hash_value": hash_value,
            "custom_payment_id": payment_id,
            "custom_actual_payment_date": getdate(renewal_payment_time) if renewal_payment_time else None,
            "custom_reference_id": renewal_reference_id if renewal_reference_id and frappe.db.exists("User", renewal_reference_id) else None,
            "custom_auth_code": webhook_values.custom_approval_code,
            "custom_invoice_type": "Renewal",
            "naming_series": "WTSP-SINV-.YYYY.-",
            "site_name": site,
            "cost_center": cost_center,
            "status": "Paid",
            "is_paid": 1,
            "is_pos": 1,
            "from_date": from_date,
            "to_date": to_date
        })

        # Get wash dates and calculate amount
        wash_days_with_count = get_wash_days_frequency(subscription_doc.custom_subscription_day_and_time)


        wash_count = get_wash_dates(from_date, to_date, wash_days_with_count)
        # frappe.log_error("wash_count:",wash_count)
        # wash_count = len(wash_dates)

        # Calculate total service quantity from plan
        total_service_qty = sum(service.qty for service in subscription_plan.custom_service) if subscription_plan.custom_service else 0

        # Determine pricing and quantity based on wash count
        if wash_count >= total_service_qty:
            amount = subscription_plan.cost  # Use plan cost directly
            qty_to_use = wash_count  # Use the predefined service quantity
        else:
            amount = calculate_invoice_amount(subscription_plan.custom_cost_per_wash, subscription_plan, wash_count)
            qty_to_use = wash_count
        # Income is booked directly (not deferred), to cash or card income by the payment mode
        income_account = get_income_account(invoice_doc.company, mode_of_payment)

        try:
            # Always add items and payments regardless of draft status
            invoice_doc.append('items', {
                'item_code': subscription_plan.item,
                'qty': 1,
                'rate': amount,
                "enable_deferred_revenue": 0,
                "income_account": income_account,
                "cost_center": invoice_doc.cost_center
            })
            if not invoice_doc.taxes_and_charges:


                sales_tax_template = frappe.db.get_value('Sales Taxes and Charges Template', {'is_default': "1"}, 'name')
                if sales_tax_template:
                    invoice_doc.taxes_and_charges = sales_tax_template
                    # Call the function to get default taxes and charges
                    from erpnext.controllers.accounts_controller import get_default_taxes_and_charges
                    
                    # Get the company from your invoice
                    company = invoice_doc.company
                    
                    # Call the function with tax_template=None to get the default taxes
                    tax_details = get_default_taxes_and_charges(
                        master_doctype="Sales Taxes and Charges Template",
                        tax_template=None,  # Pass None here to get default taxes
                        company=company
                    )
                    log_operational("tax_details create_sales_invoice_for_renewal",tax_details)
                    
                    # If tax details are returned, set the taxes in your invoice
                    if tax_details and "taxes" in tax_details:
                        for tax in tax_details["taxes"]:
                            tax["cost_center"] = cost_center
                            invoice_doc.append("taxes", tax)

            # Apply discount and coupon code from subscription document if available
            if hasattr(subscription_doc, 'custom_coupon_code') and subscription_doc.custom_coupon_code:
                # Check if coupon code exists and is valid
                coupon_expiry = frappe.db.get_value('Coupon Code', 
                                                subscription_doc.custom_coupon_code, 
                                                'valid_upto')
                if coupon_expiry and getdate(coupon_expiry) >= current_date:
                    invoice_doc.coupon_code = subscription_doc.custom_coupon_code
                    discount_account = frappe.db.get_value('Branch', site, 'custom_coupon_discount_account')
                    invoice_doc.additional_discount_account = discount_account
                else:
                    # Coupon is expired, remove from subscription
                    subscription_doc.custom_coupon_code = ""
                    subscription_doc.db_update()
                    frappe.db.commit()
                
            if hasattr(subscription_doc, 'additional_discount_percentage') and subscription_doc.additional_discount_percentage:
                invoice_doc.additional_discount_percentage = subscription_doc.additional_discount_percentage
                
            if hasattr(subscription_doc, 'additional_discount_amount') and subscription_doc.additional_discount_amount:
                invoice_doc.discount_amount = subscription_doc.additional_discount_amount

        except Exception as e:
            frappe.log_error(f"Error adding items or payments to invoice: {str(e)}")
            raise


        try:
            # Save the invoice first
            invoice_doc.save(ignore_permissions=True)

            invoice_doc.append('payments', {
                'mode_of_payment': mode_of_payment,
                'amount': invoice_doc.rounded_total or invoice_doc.grand_total
            })
            invoice_doc.save(ignore_permissions=True)

            # Set flags for submission
            invoice_doc.flags.ignore_permissions = True

            # Update vehicle services after invoice is created
            update_vehicle_services(subscription_doc, from_date, to_date, qty_to_use)
            subscription_doc.reload()  # Reload to get fresh data

            
            # Submit the document
            if invoice_doc.docstatus == 0:
                invoice_doc.submit()  # Don't pass ignore_permissions here
            
            # frappe.log_error(f"Invoice after submission - docstatus: {invoice_doc.docstatus}")
        except Exception as e:
            frappe.log_error(f"Error saving/submitting invoice: {str(e)}")
            raise


        subscription_doc.reload()
        subscription_doc.custom_mode_of_payment = mode_of_payment
        subscription_doc.custom_subscription_status = "Active"

        if not existing_paid_invoices or current_date > last_to_date:
            subscription_doc.current_invoice_start = from_date
            subscription_doc.current_invoice_end = to_date


        if webhook_values.custom_order_number:
            subscription_doc.custom_order_number = webhook_values.custom_order_number

        # Save subscription
        subscription_doc.save(ignore_permissions=True)
        frappe.db.commit()  # Commit the transaction
        deferred_total = invoice_doc.net_total + invoice_doc.discount_amount if invoice_doc.discount_amount else invoice_doc.net_total
        cost_per_wash(subscription_doc.name,deferred_total,qty_to_use)
        
        # Store total wash count in Sales Invoice
        if hasattr(invoice_doc, 'custom_total_washes'):
            invoice_doc.reload()
            invoice_doc.custom_total_washes = qty_to_use
            invoice_doc.save(ignore_permissions=True)

        if current_date == from_date and has_time:
            process_subscription_after_invoice(invoice_doc.name)
        
        
        return invoice_doc.name, subscription_doc, invoice_doc.to_date ,mode_of_payment
        
    except Exception as e:
        frappe.log_error(f"Error in create_sales_invoice_for_renewal: {str(e)}")
        raise

def update_lead_status_on_payment_actions(sales_invoice_name, custom_status):
        getting_sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice_name.name)
        getting_contact_doc = frappe.get_doc("Customer", getting_sales_invoice_doc.customer)
        fetching_lead_doc = frappe.get_all("Lead", filters={"mobile_no": getting_contact_doc.custom_mobile_number})
        if fetching_lead_doc:
            try:
                getting_lead_doc = frappe.get_doc("Lead", fetching_lead_doc)
                if getting_lead_doc.custom_lead_status != "Subscribed":
                    getting_lead_doc.custom_lead_status = custom_status
                    getting_lead_doc.save(ignore_permissions=True)
                else:
                    pass
            except Exception as e:
                frappe.log_error("Error occured on updating lead status", e)


# Change whatsapp customer details status
def update_whatsapp_customer_details_status(sales_invoice_doc, custom_status):
    try:
        getting_sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice_doc.name)
        getting_contact_doc = frappe.get_doc("Customer", getting_sales_invoice_doc.customer)
        getting_customer_doc = frappe.get_doc("WhatsApp Customer Details", getting_contact_doc.custom_mobile_number)
        if getting_customer_doc:
            getting_customer_doc.status = custom_status
        if not getting_customer_doc:
            getting_customer_doc = frappe.new_doc("WhatsApp Customer Details")
            getting_customer_doc.whatsapp_id = getting_contact_doc.custom_mobile_number if getting_contact_doc.custom_mobile_number else getting_sales_invoice_doc
            getting_customer_doc.status = custom_status
        getting_customer_doc.save(ignore_permissions=True)
    except Exception as e:
        frappe.log_error("Error occured on updating whatsapp customer details status", e)