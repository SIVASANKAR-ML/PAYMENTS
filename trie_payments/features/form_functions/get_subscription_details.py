# Gets subscription details after successful manual payment
# Params: order_id, hash_value
# Returns: Dict with subscription, customer, vehicle, and payment details

import frappe

# building_number:string,
#     flat_number:string,
#     parking_level:string,
#     parking_lot?:string,
#     wash_days?:string[],
#     wash_time?:string[],
#     wash_remainder:boolean

@frappe.whitelist(allow_guest=True)
def get_subscription_details(order_id, hash_value):
    # Get sales invoice by order_id and hash
    filtered_invoice = frappe.get_all("Sales Invoice", filters={"custom_order_id": order_id, "custom_payment_hash_value": hash_value})
    
    # Get subscription and validate existence
    sales_invoice = frappe.get_doc("Sales Invoice", filtered_invoice)
    if not sales_invoice:
        raise ValueError("Invoice Not Found")
    subscription = frappe.get_doc("Subscription",sales_invoice.subscription)
    if not subscription:
        raise ValueError("Subscription Not Found")

    # Get customer and plan details
    customer = frappe.get_doc("Customer", subscription.party)
    plans = subscription.get("plans", [])
    package_name = plans[0].plan
    package_service_per_week = plans[0].custom_package_service_per_week

    vehicle_details = []
    for vehicle in subscription.custom_vehicle_information:
        # Collect wash schedule for this vehicle
        wash_days = [row.day for row in subscription.custom_subscription_day_and_time if row.vehicle_number == vehicle.registration_number]
        wash_times = [row.time for row in subscription.custom_subscription_day_and_time if row.vehicle_number == vehicle.registration_number]
        wash_time = wash_times[0] if wash_times else ""

        vehicle_details.append({
            "car_type": vehicle.car_type,
            "registration_number": vehicle.registration_number,
            "brand_and_model": vehicle.brand_and_model,
            "car_color": vehicle.car_color,
            "parking_level": vehicle.parking_level_number,
            "parking_lot": vehicle.parking_lot_number,
            "wash_days": wash_days,
            "wash_time": wash_time
        })

    # Get location details
    if subscription.custom_vehicle_information:
        site_name = subscription.custom_vehicle_information[0].site_name
        building_number = subscription.custom_vehicle_information[0].building_number
        flat_number = subscription.custom_vehicle_information[0].flat_number
    else:
        site_name = building_number = flat_number = ""

    # Return compiled response
    response = {
        "subscription_id": subscription.name,
        "customer_name": customer.customer_name,
        "lead_id": customer.mobile_no,
        "site_name": site_name,
        "vehicle_details": vehicle_details,
        "package_service_per_week": package_service_per_week,
        "package_name": package_name,
        "sales_invoice_id": sales_invoice.name,
        "building_number": building_number,
        "flat_number": flat_number
    }
    return response

@frappe.whitelist(allow_guest=True)
def get_subscription_details_by_subscription_id(subscription_id):
    subscription = frappe.get_doc("Subscription", subscription_id)
    customer = frappe.get_doc("Customer", subscription.party)
    plans = subscription.get("plans", [])
    package_name = plans[0].plan
    package_service_per_week = plans[0].custom_package_service_per_week

    vehicle_details = []
    for vehicle in subscription.custom_vehicle_information:
        wash_days = [row.day for row in subscription.custom_subscription_day_and_time if row.vehicle_number == vehicle.registration_number]
        wash_times = [row.time for row in subscription.custom_subscription_day_and_time if row.vehicle_number == vehicle.registration_number]
        vehicle_details.append({
            "car_type": vehicle.car_type,
            "registration_number": vehicle.registration_number,
            "brand_and_model": vehicle.brand_and_model,
            "car_color": vehicle.car_color,
            "parking_level": vehicle.parking_level_number,
            "parking_lot": vehicle.parking_lot_number,
            "wash_days": wash_days,
            "wash_time": wash_times[0] if wash_times else ""
        })

    first = subscription.custom_vehicle_information[0] if subscription.custom_vehicle_information else None
    plan_doc = frappe.get_doc("Subscription Plan", package_name)
    return {
        "subscription_id": subscription.name,
        "customer_name": customer.customer_name,
        "lead_id": customer.mobile_no,
        "site_name": first.site_name if first else "",
        "vehicle_details": vehicle_details,
        "package_service_per_week": package_service_per_week,
        "package_name": package_name,
        "billing_interval": plan_doc.billing_interval,
        "plan_cost": plan_doc.cost,
        "plan_mrp": plan_doc.custom_temporary_mrp or plan_doc.cost,
        "building_number": first.building_number if first else "",
        "flat_number": first.flat_number if first else ""
    }
