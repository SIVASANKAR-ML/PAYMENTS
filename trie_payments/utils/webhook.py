"""Payment Webhook Handler
This module handles payment webhook callbacks for processing payments, renewals, and refunds.
It supports both one-time and recurring payment scenarios.
"""
from erpnext.accounts.doctype import sales_invoice
import frappe
import json
from werkzeug.wrappers import Response
from frappe.utils import getdate, nowdate, today, relativedelta
from datetime import timedelta, datetime
from erpnext.controllers.accounts_controller import get_taxes_and_charges
from trie_crm.card_change import card_change_after_payment_success
from ..external_form_payment_functions import process_successful_payment, process_failed_payment, handle_renewal_webhook_response, handle_failed_renewal_webhook_response,send_pdf_sales_invoice

@frappe.whitelist(allow_guest=True)
def payment_webhook():
    """Main webhook handler that routes GET/POST requests appropriately"""
    # Handle GET or POST request
    if frappe.request.method == "GET":
        return get()
    return post()

def get():
    """Handles webhook verification requests from payment provider
    Validates the webhook token and responds with hub challenge"""

    hub_challenge = frappe.form_dict.get("hub.challenge")
    webhook_verify_token = frappe.db.get_single_value("WhatsApp Settings", "webhook_verify_token")

    if frappe.form_dict.get("hub.verify_token") != webhook_verify_token:
        frappe.throw("Verify token does not match")

    return Response(hub_challenge, status=200)

def post():
    """Processes incoming webhook notifications for payment events
    Handles different payment scenarios including:
    - New sales
    - Renewals
    - Failed payments
    - 3D Secure authentications
    - Refunds
    """
    # Extract key information from webhook payload
    response_data = frappe.local.form_dict
    json_dump = json.dumps(response_data)
    parsed_data = json.loads(json_dump)

    status = parsed_data.get('status')
    # Get custom_data
    custom_data = parsed_data.get('custom_data', {})

    
    webhook_type = parsed_data.get('type')
    order_number = parsed_data.get('order_number')
    order_amount = parsed_data.get('order_amount')
    payment_id=parsed_data.get("id")

    try:
        # Create payment webhook log entry
        data_to_update = {
            "json_response": json_dump,
            "custom_id": parsed_data.get("id"),
            "custom_customer_name": parsed_data.get("customer_name"),
            "custom_order_number": parsed_data.get("order_number"),
            "custom_order_amount": parsed_data.get("order_amount"),
            "custom_order_currency": parsed_data.get("order_currency"),
            "custom_order_description": parsed_data.get("order_description"),
            "custom_status": parsed_data.get("status"),
            "custom_payment_response_type": parsed_data.get("type"),
            "custom_payment_time": parsed_data.get("date"),
            "custom_approval_code": parsed_data.get("approval_code"),
            "custom_reason": parsed_data.get("reason") if status == 'fail' else None,
            "custom_recurring_init_transaction_id": parsed_data.get("recurring_init_trans_id"),
            "custom_recurring_token": parsed_data.get("recurring_token")
        }
        
        creating_new_payment_webhook_log = frappe.new_doc("Payment Webhook Log")
        creating_new_payment_webhook_log.update(data_to_update)
        creating_new_payment_webhook_log.save(ignore_permissions=True)
        
        # Handle different webhook types
        if webhook_type == "sale":
            # frappe.log_error("webhook_type:",webhook_type)

            try:
                # Process successful payments
                if status == 'success':
                    # frappe.log_error("Processing successful payment with custom_data:", custom_data)
                    if custom_data and str(custom_data.get('card_change', '')).lower() == "true":
                        recurring_token = parsed_data.get('recurring_token')
                        recurring_init_trans_id = parsed_data.get('recurring_init_trans_id')

                        card_change_after_payment_success(order_number,recurring_token,recurring_init_trans_id,payment_id)
                        return

                    else:
                        # frappe.log_error("Processing regular or one-time payment")
                        # Logic for handling successful one-time and recurring payments
                        # Includes creating/updating sales invoices and subscriptions
                        order_number = parsed_data.get("order_number")
                        sales_invoice_draft = frappe.get_all("Sales Invoice",
                        filters={
                            "custom_order_id": order_number,
                            "status": "Draft"
                        },
                        order_by="creation DESC",
                        limit=1
                        )
                        if parsed_data.get("custom_data") and sales_invoice_draft:
                            draft_sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice_draft[0]["name"])
                            paid_sales_invoice_names = frappe.get_all(
                                "Sales Invoice", 
                                filters={
                                    "subscription": draft_sales_invoice_doc.subscription,
                                    "status": "Paid"
                                },
                                order_by="creation DESC"
                            )
                            is_first_invoice = len(paid_sales_invoice_names) == 0
                            if parsed_data.get("custom_data").get("one_time_payment") == "True":
                                updating_one_time_sales_invoice(parsed_data)  # handles both first & renewal
    
                                # if is_first_invoice:
                                #     updating_one_time_sales_invoice(parsed_data)
                                # else:
                                #     mode_of_payment = "One Time Payment"
                                #     handle_renewal_webhook_response(
                                #         parsed_data.get("order_number"),
                                #         parsed_data.get("hash", ""),
                                #         creating_new_payment_webhook_log,
                                #         paid_sales_invoice_names[0],
                                #         parsed_data.get("id"),
                                #         parsed_data.get("order_amount"),
                                #         draft_sales_invoice_doc,
                                #         mode_of_payment
                                #     )
                                return
                        else:
                            if sales_invoice_draft:
                                draft_sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice_draft[0]["name"])
                                paid_sales_invoice_names = frappe.get_all(
                                    "Sales Invoice",
                                    filters={
                                        "subscription": draft_sales_invoice_doc.subscription,
                                        "status": "Paid"
                                    },
                                    order_by="creation DESC"
                                )
                                
                                is_first_invoice = len(paid_sales_invoice_names) == 0

                                if is_first_invoice:
                                    hash_value = parsed_data.get("hash", "")
                                    process_successful_payment(draft_sales_invoice_doc, hash_value, creating_new_payment_webhook_log)
                                    return
                                    
                                else:
                                    mode_of_payment = "Recurring Payment"
                                    handle_renewal_webhook_response(
                                        parsed_data.get("order_number"),
                                        parsed_data.get("hash", ""),
                                        creating_new_payment_webhook_log,
                                        paid_sales_invoice_names[0],
                                        parsed_data.get("id"),
                                        parsed_data.get("order_amount"),
                                        draft_sales_invoice_doc,
                                        mode_of_payment
                                    )
                                    return
                            else:
                                # If this payment is actually settling an existing
                                # No-Payment/PDC-pending invoice (e.g. a WhatsApp
                                # payment link sent from the Pending Payment
                                # Collection flow), clear that PDC instead of
                                # falling through to renewal-invoice creation below.
                                from trie_crm.api import find_pending_pdc_invoice, collect_pending_payment
                                pdc_invoice_no, pdc_log_name = find_pending_pdc_invoice(
                                    custom_data.get("invoice_no") if custom_data else None
                                )
                                if pdc_log_name:
                                    collect_pending_payment(
                                        pending_payment=pdc_log_name,
                                        payment_type="One Time Payment",
                                        amount=order_amount,
                                        posting_date=today(),
                                    )
                                    return
                                if custom_data and str(custom_data.get('card_change', '')).lower() == "true":
                                    frappe.log_error(
                                        f"Card change webhook reached renewal path for order {order_number}. Skipping.",
                                        "Card Change Misrouted"
                                    )
                                    return


                                # paid_sales_invoice_names = frappe.get_last_doc(
                                #     "Sales Invoice",
                                #     filters={
                                #         "custom_order_id": order_number,
                                #         "status": "Paid"
                                #     },
                                #     order_by="creation DESC"
                                # ) or []
                                paid_sales_invoice_names = frappe.get_all(
                                    "Sales Invoice",
                                    filters={
                                        "custom_order_id": order_number,
                                        "status": "Paid"
                                    },
                                    order_by="creation DESC",
                                    limit=1
                                )

                                paid_sales_invoice = paid_sales_invoice_names[0] if paid_sales_invoice_names else None


                                subscription_custom_data = custom_data.get("subscription")
                                paid_sales_invoice_names_subscription = frappe.get_all(
                                    "Sales Invoice",
                                    filters={
                                        "subscription": subscription_custom_data,
                                        "status": "Paid"
                                    },
                                    order_by="creation DESC",
                                    limit=1
                                )

                                paid_sales_invoice_subscription = (
                                    paid_sales_invoice_names_subscription[0]
                                    if paid_sales_invoice_names_subscription
                                    else None
                                )
                                # paid_sales_invoice_names_subscription = frappe.get_last_doc(
                                #     "Sales Invoice", 
                                #     filters={
                                #         "subscription": subscription_custom_data,
                                #         "status": "Paid"
                                #     },
                                #     order_by="creation DESC"
                                # )
                                draft_sales_invoice_doc = None
                                mode_of_payment = "Recurring Payment"
                                invoice_to_use = (
                                    paid_sales_invoice
                                    if paid_sales_invoice
                                    else paid_sales_invoice_subscription
                                )

                                handle_renewal_webhook_response(
                                    parsed_data.get("order_number"),
                                    parsed_data.get("hash", ""),
                                    creating_new_payment_webhook_log,
                                    invoice_to_use,
                                    parsed_data.get("id"),
                                    parsed_data.get("order_amount"),
                                    draft_sales_invoice_doc,
                                    mode_of_payment
                                )
                                
                                # handle_renewal_webhook_response(
                                #     parsed_data.get("order_number"),
                                #     parsed_data.get("hash", ""),
                                #     creating_new_payment_webhook_log,
                                #     paid_sales_invoice_names if paid_sales_invoice_names else paid_sales_invoice_names_subscription,
                                #     parsed_data.get("id"),
                                #     parsed_data.get("order_amount"),
                                #     draft_sales_invoice_doc,
                                #     mode_of_payment
                                # )
                                
                                return
                        
        
                elif status == 'fail':
                    # Handle failed payments for both new and renewal scenarios
                    # Fetch Sales Invoice related to the order number
                    sales_invoice_names = frappe.get_all(
                        "Sales Invoice", 
                        filters={"custom_order_id": parsed_data.get("order_number")},
                        pluck="name"
                    )
                    if sales_invoice_names:
                        sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice_names[0])
                        amount = parsed_data.get("order_amount")
                        hash_value = parsed_data.get("hash", "")
                        
                        if len(sales_invoice_names) == 1 and sales_invoice_doc.status == "Draft":
                            # Handle failed payment for new invoice
                            process_failed_payment(sales_invoice_doc, hash_value, amount, parsed_data.get("reason"))
                        else:
                            paid_sales_invoice_names = frappe.get_all(
                                "Sales Invoice", 
                                filters={
                                    "custom_order_id": parsed_data.get("order_number"),
                                    "status": "Paid"
                                },
                                pluck="name",
                                order_by="creation DESC"
                            )
                            if len(sales_invoice_names) >= 1 and paid_sales_invoice_names:
                                # Handle failed renewal
                                handle_failed_renewal_webhook_response(
                                    parsed_data.get("order_number"),
                                    parsed_data.get("reason"),
                                    amount
                                )
                        return
        
            except ValueError or Exception as e:
                frappe.log_error("Error on processing sale type payment", e)

                    
        if webhook_type == "3ds":
            # Handle 3D Secure authentication results
            try:
                if status == 'success': 
                    return
                if status == 'fail':
                    frappe.log_error("Failed 3ds payment")
                    return
            except Exception as e:
                frappe.log_error("Error on processing 3ds type payment", e)


        if webhook_type == "refund":
            # Process refund notifications
            try:
                if status == 'success':
                    frappe.log_error("Refund type payment", sales_invoice_names)
                    # sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice_names[0])
                    # process_successful_payment(sales_invoice_doc, parsed_data.get("hash", ""), creating_new_payment_webhook_log, refund=True)
                    # return sales_invoice_doc.name
            except Exception as e:
                frappe.log_error("Error on processing refund type payment", e)


    except KeyError as k:
        frappe.log_error(f"KeyError: Missing field in data: {str(k)}")
    except IndexError as i:
        frappe.log_error(f"IndexError: List index out of range: {str(i)}")
    except Exception as e:
        frappe.log_error(f"Unexpected error: {str(e)}")
        
    return 




# --------------------------------------------------------------------------------------------   One-Time Payment


# from datetime import datetime, timedelta
# from frappe.utils import getdate, nowdate


def updating_one_time_sales_invoice(parsed_data):
    """Updates sales invoice for one-time payments
    Handles:
    - Setting payment details
    - Updating invoice dates
    - Applying taxes
    - Managing subscription periods
    - Triggering post-payment workflows
    - Updating vehicle services
    """
    try:
        from trie_crm.invoice_and_service_job import get_billing_interval_details,has_sufficient_time,find_next_service_day
        
        # Extract basic invoice information
        invoice_no = parsed_data.get("custom_data").get("invoice_no")
        order_no = parsed_data.get("order_number")
        hash_value = parsed_data.get("hash")
        sales_invoice = frappe.get_doc("Sales Invoice", invoice_no)
        if sales_invoice.docstatus == 1:
            frappe.log_error(
                f"Skipping duplicate one-time payment webhook for already-submitted invoice {invoice_no}, order {order_no}",
                "One Time Payment Duplicate Webhook"
            )
            return
        current_date = datetime.strptime(frappe.utils.today(), "%Y-%m-%d").date()
        raw_payment_date = parsed_data.get("date")

        # Update payment details
        posting_date = getdate(nowdate())
        sales_invoice.custom_payment_hash_value = hash_value
        sales_invoice.custom_payment_id = parsed_data.get("id")
        sales_invoice.custom_actual_payment_date = getdate(raw_payment_date) if raw_payment_date else None
        sales_invoice.custom_auth_code = parsed_data.get("approval_code")
        sales_invoice.is_paid = 1
        sales_invoice.is_pos = 1
        sales_invoice.status = "Paid"
        sales_invoice.posting_date = posting_date

        # sales_tax_template = frappe.db.get_value('Sales Taxes and Charges Template', {'is_default': "1"}, 'name')
        # if sales_tax_template:
        #     sales_invoice.taxes_and_charges = sales_tax_template
        #     # Call the function to get default taxes and charges
        #     from erpnext.controllers.accounts_controller import get_default_taxes_and_charges
            
        #     # Get the company from your invoice
        #     company = sales_invoice.company
            
        #     # Call the function with tax_template=None to get the default taxes
        #     tax_details = get_default_taxes_and_charges(
        #         master_doctype="Sales Taxes and Charges Template",
        #         tax_template=None,  # Pass None here to get default taxes
        #         company=company
        #     )
        #     frappe.log_error("tax_details",tax_details)
            
        #     # If tax details are returned, set the taxes in your invoice
        #     if tax_details and "taxes" in tax_details:
        #         for tax in tax_details["taxes"]:
        #             sales_invoice.append("taxes", tax)


        # # Add payment entry
        # frappe.log_error("invoice amount",sales_invoice.grand_total)
        payment_item = {
            "doctype": "Sales Invoice Payment",
            "mode_of_payment": "One Time Payment",
            "amount": sales_invoice.rounded_total or sales_invoice.grand_total
        }
        sales_invoice.append("payments", payment_item)

        # Get subscription details
        subscription_doc = frappe.get_doc("Subscription", sales_invoice.subscription)
        subscription_plan_name = subscription_doc.plans[0].plan if subscription_doc.plans else None
        subscription_plan = frappe.get_doc("Subscription Plan", subscription_plan_name) if subscription_plan_name else None

        # Carry the Reference Id from the subscription onto the invoice
        if subscription_doc.custom_reference_id and frappe.db.exists("User", subscription_doc.custom_reference_id):
            sales_invoice.custom_reference_id = subscription_doc.custom_reference_id

        # Calculate datespayment_webhook
        try:
            paid_sales_invoice = frappe.get_last_doc(
                "Sales Invoice",
                filters={
                    "subscription": sales_invoice.subscription,
                    "status": "Paid",
                }
            )
        except frappe.DoesNotExistError:
            paid_sales_invoice = None

        if paid_sales_invoice:
            current_invoice_end = frappe.get_value("Subscription", sales_invoice.subscription, "current_invoice_end")
            if isinstance(current_invoice_end, str):
                current_invoice_end = datetime.strptime(current_invoice_end, "%Y-%m-%d").date()
            if paid_sales_invoice.to_date >= posting_date:
                from_date = paid_sales_invoice.to_date + timedelta(days=1)
            else:
                from_date = posting_date

            # Get billing interval details
            days_to_add = get_billing_interval_details(sales_invoice.subscription, from_date)
            if days_to_add is not None:
                to_date = from_date + timedelta(days=days_to_add)
            else:
                to_date = current_invoice_end - timedelta(days=1)
        else:
            from_date = posting_date
            days_to_add = get_billing_interval_details(sales_invoice.subscription, from_date)
            fallback_days = (subscription_plan.billing_interval_count - 1) if subscription_plan else 29
            to_date = from_date + timedelta(days=days_to_add if days_to_add is not None else fallback_days)

        if days_to_add is None:
            days_to_add = (subscription_plan.billing_interval_count - 1) if subscription_plan else 29

        has_time = True

        # Check if current date equals from_date and adjust if needed
        if current_date == from_date:
            current_day_name = current_date.strftime("%A")
            is_wash_day = any(day.day == current_day_name for day in subscription_doc.custom_subscription_day_and_time)
            
            if is_wash_day:
                wash_time = next((day.time for day in subscription_doc.custom_subscription_day_and_time 
                                if day.day == current_day_name), None)
                
                has_time = has_sufficient_time(sales_invoice.site_name, frappe.utils.nowtime(), wash_time)
                if not has_time:
                    next_wash_day = find_next_service_day(subscription_doc, current_date)
                    from_date = next_wash_day
                to_date= from_date + timedelta(days=days_to_add)

        # Update sales invoice
        sales_invoice.from_date = from_date
        sales_invoice.to_date = to_date
        sales_invoice.save(ignore_permissions=True)
        
        
              
        updating_subscription_after_payment(sales_invoice.subscription, sales_invoice.from_date, sales_invoice.to_date, sales_invoice,has_time)

    except Exception as e:
        frappe.log_error("Error in updating_one_time_sales_invoice", str(e))
        raise


def updating_subscription_after_payment(subscription, from_date, to_date, sales_invoice, has_time):
    """Updates subscription details after successful payment
    
    Handles:
    - Subscription status updates
    - Date adjustments
    - WhatsApp notifications
    - PDF invoice sending
    - Service job processing (if applicable)
    """
    from trie_crm.invoice_and_service_job import (
        process_subscription_after_invoice,
        update_vehicle_services_from_plan
    )
    from trie_crm.triecrm_functions import get_wash_dates,cost_per_wash,get_wash_days_frequency

    subscription_doc = frappe.get_doc("Subscription", subscription)
    
    # Update subscription and vehicle services
    # wash_days = [wash_day.day for wash_day in subscription_doc.custom_subscription_day_and_time]
    wash_days_with_count = get_wash_days_frequency(subscription_doc.custom_subscription_day_and_time)

    wash_dates = get_wash_dates(from_date, to_date, wash_days_with_count)
    


    subscription_doc.set("custom_vehicle_service", [])
    # needs_special_pricing = True
    update_vehicle_services_from_plan(subscription_doc,wash_dates,from_date,to_date)
    

    # Update subscription status and dates
    if not subscription_doc.custom_pause_expiry_date and subscription_doc.custom_subscription_paused == 1:
        subscription_doc.custom_subscription_paused = 0
    subscription_doc.custom_subscription_status = "Active"
    subscription_doc.custom_mode_of_payment = "One Time Payment"

    subscription_doc.save(ignore_permissions=True)
    
    current_date = datetime.strptime(frappe.utils.today(), "%Y-%m-%d").date()
    
    # Process service job and get updated dates if needed
    if current_date == from_date and has_time:
        try:
            new_dates_key = "{}_dates".format(subscription_doc.name)
            frappe.cache().delete_value(new_dates_key)   # ← clear stale cache FIRST
            
            process_subscription_after_invoice(sales_invoice.name)
            subscription_doc.reload()
            
            new_invoice_date = frappe.cache().get_value(new_dates_key)
            
            if new_invoice_date and 'start_date' in new_invoice_date and 'end_date' in new_invoice_date:
                from_date = new_invoice_date['start_date'].strftime('%Y-%m-%d')
                to_date = new_invoice_date['end_date'].strftime('%Y-%m-%d')
        except Exception as e:
            frappe.log_error("Error processing subscription after invoice", str(e))
    
    today = getdate(nowdate())
    if getdate(from_date) <= today:
        subscription_doc.current_invoice_start = from_date
        subscription_doc.current_invoice_end = to_date
    else:
        # Advance/future payment — store next start date, don't overwrite active period
        subscription_doc.custom_next_start_date = from_date

    if sales_invoice.custom_order_id:
        subscription_doc.custom_order_number = sales_invoice.custom_order_id

    subscription_doc.save(ignore_permissions=True)
    
    # Update sales invoice dates
    sales_invoice.from_date = from_date
    sales_invoice.to_date = to_date
    sales_invoice.save(ignore_permissions=True)
    sales_invoice.submit()
    frappe.db.commit()

    try:  
        deferred_total = sales_invoice.net_total + sales_invoice.discount_amount if sales_invoice.discount_amount else sales_invoice.net_total
        cost_per_wash(subscription_doc.name,deferred_total,wash_dates)
    except Exception as e:
        frappe.log_error("Error in cost_per_wash after one-time payment submit", str(e))
    
    
    # Send notifications
    try:
        apps = frappe.get_single("Installed Applications").installed_applications
        app_array = [app.app_name for app in apps if app.app_name in ["trie_whatsapp", "trie_crm"]]
        
        if app_array:
            from trie_whatsapp.whatsapp_templates import sending_updated_pdf_sales_invoice, successfully_created_subscription
            from trie_whatsapp.sms_actions import subscription_message, send_pdf_sales_invoice
            
            customer_name = frappe.get_value("Customer", subscription_doc.party, ["customer_name"])
            
            # Send WhatsApp notifications
            successfully_created_subscription(subscription_doc.custom_whatsapp_number)
            sending_updated_pdf_sales_invoice(subscription_doc.custom_whatsapp_number, sales_invoice.name)
            subscription_message(subscription_doc.custom_whatsapp_number)
            send_pdf_sales_invoice(subscription_doc.custom_whatsapp_number, customer_name, sales_invoice.name)
    except Exception as e:
        frappe.log_error("Error sending notificnotificationsations", str(e))