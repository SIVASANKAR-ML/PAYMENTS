import frappe
from werkzeug.wrappers import Response

@frappe.whitelist(allow_guest=True)
def get_latest_subscription(whatsapp_id):
    # Get customer document using WhatsApp ID
    getting_customer_doc = frappe.get_doc("WhatsApp Customer Details", whatsapp_id)
    
    # Check if customer has successful payment status
    if getting_customer_doc.status == "Payment Success":
        # Get all subscriptions for this WhatsApp number
        all_subscriptions = frappe.get_all("Subscription", 
            filters={"custom_whatsapp_number": whatsapp_id}, 
            pluck="name")
        
        # Iterate through each subscription
        for subscription in all_subscriptions:
            fetching_subscription_doc = frappe.get_doc("Subscription", subscription)
            if fetching_subscription_doc:
                # Check if subscription day/time is not set (new subscription)
                if (fetching_subscription_doc.custom_subscription_day_and_time and 
                    not fetching_subscription_doc.custom_subscription_day_and_time[0].get('day')):
                    
                    # Process only WhatsApp channel subscriptions
                    if fetching_subscription_doc.custom_subscription_channel == "WhatsApp":
                        # Get the latest paid sales invoice for this subscription
                        sales_invoice_getting_last_doc = frappe.get_last_doc(
                            "Sales Invoice", 
                            filters={
                                "custom_order_id": fetching_subscription_doc.custom_order_number, 
                                "status": "Paid"
                            }
                        )

                        # Create list of vehicle details from subscription
                        vehicle_details = [{
                            "car_type": vehicle.car_type,
                            "registration_number": vehicle.registration_number,
                            "brand_and_model": vehicle.brand_and_model,
                            "car_color": vehicle.car_color
                        } for vehicle in fetching_subscription_doc.custom_vehicle_information]

                        # Get customer name from Customer doctype
                        getting_customer_name_value = frappe.get_value(
                            "Customer", 
                            fetching_subscription_doc.party, 
                            ["customer_name"]
                        )

                        # Extract plan details
                        plan_name = fetching_subscription_doc.get("plans", [])
                        for plan in plan_name:
                            getting_plan_value = plan.plan
                            getting_package_service_per_week = plan.custom_package_service_per_week
                        
                        # Get total number of washes
                        total_number_of_washes = fetching_subscription_doc.get("custom_vehicle_service", [])
                        for plan in total_number_of_washes:
                            getting_total_number_of_washes_value = plan.qty

                        # Prepare response with subscription details
                        response = {
                            "subscription_id": fetching_subscription_doc.name,
                            "customer_name": getting_customer_name_value,
                            "site_name": (fetching_subscription_doc.custom_vehicle_information[0].site_name 
                                        if fetching_subscription_doc.custom_vehicle_information else ""),
                            "vehicle_details": vehicle_details,
                            "package_service_per_week": str(getting_package_service_per_week),
                            "total_number_of_washes": getting_total_number_of_washes_value,
                            "package_name": getting_plan_value,
                            "sales_invoice_id": sales_invoice_getting_last_doc.name
                        }

                        return response
                    else:
                        # Skip if not WhatsApp channel
                        continue
                else:
                    # Skip if subscription day/time is already set
                    continue
            else:
                return Response("Subscription Updated", status=400)
    else:
        return Response("Subscription Not Found", status=400)
    
    