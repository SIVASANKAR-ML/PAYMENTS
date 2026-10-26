import frappe


def unpaid_subscription(doc, events):
    if doc.is_new():
        return
        
    # Check if both 'end_time' and 'status' have changed
    if doc.has_value_changed('status') == "Unpaid":
        send_subscription_unpaid_message(doc, events)


def send_subscription_unpaid_message(doc, events):
    subscription = frappe.get_doc("Subscriptions", doc.name)
    current_date = frappe.utils.today()
    sales_invoice = frappe.get_last_doc("Sales Invoice", filters= {"subscription": subscription})

    if sales_invoice.status == "Paid":
        if sales_invoice.to_date <= current_date:
            if subscription.custom_notifications_preference == 1 and subscription.custom_scheduler_id:
                try:
                    customer_name = frappe.get_value(
                        "Customer",
                        filters={"custom_mobile_number": subscription.custom_whatsapp_number},
                        fieldname="customer_name")
                    for plan_detail in subscription.plans:
                        service_plan = plan_detail.plan
                    for vehicle_info in subscription.custom_vehicle_information:
                        vehicle_number = vehicle_info.registration_number
                    # Prefer TotalPay-owned identifiers — never rewritten by our
                    # own code — over custom_order_number, which is pinned to the
                    # subscription's original order number and won't match a
                    # later failed-attempt's Payment Webhook Log.
                    log_filters = {"custom_status": "fail"}
                    if subscription.custom_recurring_init_transaction_id:
                        log_filters["custom_recurring_init_transaction_id"] = subscription.custom_recurring_init_transaction_id
                    elif subscription.custom_recurring_token:
                        log_filters["custom_recurring_token"] = subscription.custom_recurring_token
                    else:
                        log_filters["custom_order_number"] = subscription.custom_order_number

                    try:
                        payment_webhook_log = frappe.get_last_doc("Payment Webhook Log", filters=log_filters)
                    except frappe.DoesNotExistError:
                        return
                    if payment_webhook_log.custom_status == "fail":
                        value = [customer_name, subscription.name, service_plan, vehicle_number, payment_webhook_log.custom_reason]
                        apps = frappe.get_single("Installed Applications").installed_applications
                        app_array = [app.app_name for app in apps if app.app_name in ["trie_whatsapp"]]
                        if app_array:
                            # Move the import statement inside the function
                            # from trie_whatsapp.whatsapp_templates import failed_auto_renewal_webhook_response
                            # from trie_whatsapp.sms_actions import payment_renewal_failure
                            # failed_auto_renewal_webhook_response(subscription.custom_whatsapp_number, value)
                            # payment_renewal_failure(subscription.custom_whatsapp_number, customer_name, subscription.name, service_plan, vehicle_number, payment_webhook_log.custom_reason)
                            e = payment_webhook_log.as_json()
                            frappe.log_error(f"Payment Failed for {subscription.name}", e)
                        else:
                            pass
                except Exception as e:
                    frappe.log_error("Error on handling failed renewal webhook response", e)
                    pass
