import frappe, random
import datetime as dt
import json
import requests
import hashlib, re
from trie_crm.invoice_and_service_job import get_billing_interval_details, has_sufficient_time, find_next_service_day
from trie_crm.triecrm_functions import get_contract_end_date, get_income_account
from datetime import timedelta
from frappe.utils import getdate, today
from trie_crm.utils import log_operational


@frappe.whitelist(allow_guest=True)
def create_subscription(whatsapp_contact_id, building_number,flat_number, details, custom_wash_reminder_preference, remarks,payment_type,coupon_code=None):
    """
    Creates a new subscription for car wash services via WhatsApp.
    
    Args:
        whatsapp_contact_id (str): Customer's WhatsApp number
        building_number (str): Building identifier
        flat_number (str): Flat/apartment number
        parking_level (str): Parking level identifier
        parking_lot (str): Parking lot number
        wash_days (str/list): Preferred wash days
        wash_time (str): Preferred wash time
        custom_wash_reminder_preference (int): Reminder settings
        remarks (str): Additional notes
        
    Returns:
        dict: Contains payment URL and subscription details
    """
    try:
        # Check for existing unpaid subscriptions for this WhatsApp number
        subscriptions = frappe.get_all("Subscription", 
            filters={"custom_whatsapp_number": whatsapp_contact_id, "custom_mode_of_payment": ["is", "not set"]})

        # Fetch customer and package details
        customer_details = frappe.get_doc("WhatsApp Customer Details", whatsapp_contact_id)
        package_id = customer_details.package_deal
        getting_subscription_plan = frappe.get_doc("Subscription Plan", package_id)
        service_table = getting_subscription_plan.custom_service
        service_name = service_table[0].services if service_table and len(service_table) > 0 else None

        # Check if customer exists, if not create new customer
        existing_customer = frappe.get_all("Customer", filters={"custom_mobile_number": whatsapp_contact_id}, limit=1)
        if existing_customer:
            customer_doc = frappe.get_doc("Customer", existing_customer)
        else:
            # Create new customer document with basic details
            new_customer = frappe.new_doc("Customer")
            new_customer.customer_name = f"{customer_details.first_name} {customer_details.last_name}"
            new_customer.custom_contract_number = "Nil - WhatsApp"
            new_customer.custom_mobile_number = customer_details.name
            new_customer.customer_type = "Individual"
            new_customer.customer_group = "Individual"
            new_customer.territory = "United Arab Emirates"

            if customer_details.car_brand_and_model == "":
                car_brand_value = customer_details.custom_car_brand
                car_model_value = customer_details.custom_car_model
                new_customer.append('custom_vehicle_information', {
                    'site_name': customer_details.site_name,
                    'car_type': customer_details.car_type,
                    'registration_number': customer_details.car_registration_number,
                    'other_brand_and_model': f"{car_brand_value} {car_model_value}",
                    'car_color': customer_details.car_color
                })
            else:
                new_customer.append('custom_vehicle_information', {
                    'site_name': customer_details.site_name,
                    'car_type': customer_details.car_type,
                    'registration_number': customer_details.car_registration_number,
                    'brand_and_model': customer_details.car_brand_and_model,
                    'car_color': customer_details.car_color
                })

            new_customer.save(ignore_permissions = True)

        # Initialize new subscription with basic details
        if customer_details:
            new_subscription = frappe.new_doc("Subscription")
            # Set subscription metadata
            new_subscription.party_type = "Customer"
            new_subscription.company = "TriE"
            new_subscription.custom_whatsapp_number = whatsapp_contact_id
            new_subscription.custom_remaining_pause_days = 60
            new_subscription.custom_subscription_channel = "WhatsApp"
            new_subscription.custom_subscription_status = "Unpaid"
            new_subscription.custom_notifications_preference = 1
            new_subscription.party = customer_doc.name if existing_customer else new_customer.name
            new_subscription.status = "Unpaid"
            new_subscription.custom_wash_reminder_preference = custom_wash_reminder_preference
            new_subscription.custom_remarks=remarks
            new_subscription.custom_coupon_code=coupon_code
            new_subscription.custom_posting_date = frappe.utils.nowdate()
            if customer_details:
                new_subscription.custom_email = customer_details.email_id
            else:
                pass

            # Set the subscription dates
            new_subscription.start_date = frappe.utils.nowdate()
            end_date = dt.datetime.strptime(frappe.utils.nowdate(), "%Y-%m-%d") + dt.timedelta(days=1825)
            new_subscription.end_date = end_date.strftime("%Y-%m-%d")

            # Append plan information
            new_subscription.append('plans', {
                'plan': getting_subscription_plan.name,
                'qty': "1",
                'custom_package_service_per_week': getting_subscription_plan.custom_service_per_week,
                'custom_package_price': getting_subscription_plan.cost
            })
            
            
            # Append vehicle information based on whether a specific brand and model are provided
            for car in customer_details.vehicle_details:
                if not car.brand_and_model or car.brand_and_model == "Other":
                    new_subscription.append('custom_vehicle_information', {
                        'site_name': customer_details.site_name,
                        'car_type': car.car_type,
                        'registration_number': car.registration_number,
                        'other_brand_and_model': "Other",
                        'car_color': car.car_color,
                        'custom_input_car_brand': car.car_brand,
                        'custom_input_car_model': car.car_model
                    })
                else:
                    try:
                        brand_and_model_doc = frappe.get_doc("Car Brand And Model", car.brand_and_model)
                        car_type = brand_and_model_doc.car_type
                    except frappe.DoesNotExistError:
                        car_type = car.car_type 

                    new_subscription.append('custom_vehicle_information', {
                        'site_name': customer_details.site_name,
                        'car_type': car_type,
                        'registration_number': car.registration_number,
                        'brand_and_model': car.brand_and_model,
                        'car_color': car.car_color
                    })
            site_name=customer_details.site_name
            new_subscription.cost_center = frappe.db.get_value('Cost Center', {'custom_branch': site_name}, 'name')

            # Fetch item details for the plan package
            getting_quantity_from_item = frappe.get_doc("Item", package_id)
            child_table_records = getting_quantity_from_item.get("custom_services_table", [])

            # Append service details to the subscription
            for plan in child_table_records:
                getting_qty_value = plan.qty
            for car in customer_details.vehicle_details:
                new_subscription.append('custom_vehicle_service', {
                    'vehicle_number': car.registration_number,
                    'service':service_name,
                    'qty': "0"
                })

            # Initialize the response dictionary
            response = {
                "vehicle_details_and_location_details": [],
                "wash_day_details": [],
                "number_of_days": new_subscription.number_of_days
            }

            new_subscription.set("custom_subscription_day_and_time", []) 
            if isinstance(details, str):
                details = json.loads(details)

            # Updating vehicle details with bay and zone information
            if new_subscription.custom_vehicle_information:
                for vehicle in new_subscription.custom_vehicle_information:
                    reg_no = vehicle.registration_number
                    if reg_no in details:
                        v_details = details[reg_no]
                        vehicle.flat_number = flat_number
                        vehicle.building_number = building_number
                        vehicle.parking_level_number = v_details.get("parking_level")
                        vehicle.parking_lot_number = v_details.get("parking_lot")
                        log_operational(f"Vehicle Details: Flat: {flat_number}, Building: {building_number}, Parking Level: {v_details.get('parking_level')}, Parking Lot: {v_details.get('parking_lot')} ",f"Vehicle details updated for registration number {reg_no}")

                        # Split wash_days into a list if it's a string
                        v_wash_days = v_details.get("wash_days", [])
                        if isinstance(v_wash_days, str):
                            v_wash_days = [day.strip() for day in v_wash_days.split(",")]

                        v_wash_time = v_details.get("wash_time")
                        # frappe.log_error("Wash Time", v_wash_time)
       
                        # Updating wash day and time details for each vehicle
                        for wash_day in v_wash_days:
                            new_subscription.append("custom_subscription_day_and_time", {
                                "vehicle_number": reg_no,
                                "day": wash_day,
                                "time": v_wash_time
                            })

                        response["wash_day_details"].append({
                            "vehicle_number": reg_no,
                            "wash_day": v_wash_days,
                            "time": v_wash_time
                        })

            try:
                # Fetch all bays
                all_bays = frappe.get_all("Bay", fields=["name", "zone"])
                
                # Updating vehicle details with bay and zone information
                if new_subscription.custom_vehicle_information:
                    for vehicle in new_subscription.custom_vehicle_information:
                        reg_no = vehicle.registration_number
                        
                        # Only process if we have parking details for this vehicle
                        if details and reg_no in details and vehicle.flat_number and vehicle.registration_number:
                            parking_info = details[reg_no]
                            parking_level = parking_info.get("parking_level")
                            
                            bay_name = None
                            zone_name = None
                            
                            # Find matching bay for this specific vehicle
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
                                
                            if bay_name:
                                vehicle.bay_name = bay_name
                                vehicle.zone_name = zone_name
                            else:
                                pass
                
                            
                # Set flags to ignore validation and mandatory field checks
                # new_subscription.flags.ignore_validate = True
                new_subscription.save(ignore_permissions=True)
            except Exception as inner_error:
                frappe.log_error("Error updating vehicle details", inner_error)
                raise "Error on updating vehicle location"
                

            # If there's a WhatsApp number, handle related updates on the Customer doctype
            try:
                if new_subscription.custom_whatsapp_number:
                    whatsapp_no = new_subscription.custom_whatsapp_number
                    # whatsapp_contact_id = whatsapp_no if whatsapp_no.startswith('+') else '+' + whatsapp_no

                    # Iterate over the vehicle information in the subscription document
                    for vehicle_info in new_subscription.custom_vehicle_information:
                        registration_number_value = vehicle_info.registration_number

                        if registration_number_value:
                            whatsapp_customer = frappe.get_all("WhatsApp Customer Details", filters={"whatsapp_id": whatsapp_no})
                            if whatsapp_customer:
                                whatsapp_customer_doc = frappe.get_doc("WhatsApp Customer Details", whatsapp_customer[0].name)
                                whatsapp_customer_doc.building_number = vehicle_info.building_number
                                whatsapp_customer_doc.flat_number = vehicle_info.flat_number
                                whatsapp_customer_doc.custom_parking_level_number = vehicle_info.parking_level_number
                                whatsapp_customer_doc.zone_name = vehicle_info.zone_name

                                for vehicle_detail in whatsapp_customer_doc.vehicle_details:
                                    if vehicle_detail.registration_number == registration_number_value:
                                        # Update vehicle details directly
                                        vehicle_detail.flat_number = vehicle_info.flat_number
                                        vehicle_detail.building_number = vehicle_info.building_number
                                        vehicle_detail.parking_lot = vehicle_info.parking_lot_number
                                        vehicle_detail.parking_level_number = vehicle_info.parking_level_number
                                whatsapp_customer_doc.save(ignore_permissions=True)
                                frappe.db.commit()

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

                            if not customer_list:
                                # Create a new customer if none exists
                                customer_name = f"{customer_details.first_name} {customer_details.last_name}"
                                new_customer = frappe.new_doc("Customer")
                                new_customer.customer_name = customer_name
                                new_customer.custom_contract_number = "Nil - WhatsApp"
                                new_customer.custom_mobile_number = customer_details.name
                                new_customer.customer_type = "Individual"
                                new_customer.customer_group = "Individual"
                                new_customer.territory = "United Arab Emirates"
                    
                                if customer_details.car_brand_and_model == "":
                                    car_brand_value = customer_details.custom_car_brand
                                    car_model_value = customer_details.custom_car_model
                                    new_customer.append('custom_vehicle_information', {
                                        'site_name': customer_details.site_name,
                                        'car_type': customer_details.car_type,
                                        'registration_number': customer_details.car_registration_number,
                                        'other_brand_and_model': f"{car_brand_value} {car_model_value}",
                                        'car_color': customer_details.car_color
                                    })
                                else:
                                    new_customer.append('custom_vehicle_information', {
                                        'site_name': customer_details.site_name,
                                        'car_type': customer_details.car_type,
                                        'registration_number': customer_details.car_registration_number,
                                        'brand_and_model': customer_details.car_brand_and_model,
                                        'car_color': customer_details.car_color
                                    })
                    
                                new_customer.save(ignore_permissions = True)

            except Exception as e:
                frappe.log_error("Error on updating customer vehicle details", e)
                raise "Customer Details not updated"

            if coupon_code:
                log_operational("Coupon Code",coupon_code)


            # Generating payment url
            payment_link, order_number = generate_payment_link(whatsapp_contact_id, customer_details, package_id, customer_doc.customer_name, new_subscription,payment_type,coupon_code=coupon_code)
            

            new_subscription.custom_order_number = order_number
            new_subscription.custom_payment_link_url = payment_link["redirect_url"] if payment_link["redirect_url"] else None
            # Set flags to ignore validation and mandatory field checks
            new_subscription.flags.ignore_validate = True
            new_subscription.save(ignore_permissions=True)

            return {
                "redirect_url" : payment_link["redirect_url"],
                "subscription_details": new_subscription
            }

        else:
            create_whatsapp_customer = frappe.new_doc("WhatsApp Customer Details")
            create_whatsapp_customer.whatsapp_id = whatsapp_contact_id
            create_whatsapp_customer.save(ignore_permissions=True)
            frappe.db.commit()

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Subscription Creation Error")



def generate_payment_link(whatsapp_id, customer_details, package_id, customer_name, subscription,payment_type,coupon_code=None):
    """
    Generates payment link for subscription and creates sales invoice.
    
    Args:
        whatsapp_id (str): Customer's WhatsApp ID
        customer_details (obj): Customer information document
        package_id (str): Selected package identifier
        customer_name (str): Customer's full name
        subscription (obj): Subscription document
        
    Returns:
        tuple: (payment_link_dict, order_number)
    """
    # Create a new draft Sales Invoice document
    sales_invoice_doc = frappe.new_doc("Sales Invoice")
    sales_invoice_doc.customer = customer_name
    sales_invoice_doc.status = "Draft"
    sales_invoice_doc.posting_date = frappe.utils.nowdate()
    sales_invoice_doc.naming_series = "WTSP-SINV-.YYYY.-"
    sales_invoice_doc.custom_invoice_type = "New"
    sales_invoice_doc.site_name = customer_details.site_name
    sales_invoice_doc.subscription = subscription.name
    if coupon_code:
        sales_invoice_doc.coupon_code=coupon_code
        log_operational("link generate with coupon code",coupon_code)
        site_name=customer_details.site_name
        discount_account = frappe.db.get_value('Branch', site_name, 'custom_coupon_discount_account')
        sales_invoice_doc.additional_discount_account = discount_account

    if customer_details.site_name:
        cost_center = frappe.db.get_value('Cost Center', {'custom_branch': customer_details.site_name}, 'name')
        if cost_center:
            sales_invoice_doc.cost_center = cost_center
    if not sales_invoice_doc.taxes_and_charges:
        sales_tax_template = frappe.db.get_value('Sales Taxes and Charges Template', {'is_default': "1"}, 'name')
        if sales_tax_template:
            sales_invoice_doc.taxes_and_charges = sales_tax_template
            # Call the function to get default taxes and charges
            from erpnext.controllers.accounts_controller import get_default_taxes_and_charges
            
            # Get the company from your invoice
            company = sales_invoice_doc.company
            
            # Call the function with tax_template=None to get the default taxes
            tax_details = get_default_taxes_and_charges(
                master_doctype="Sales Taxes and Charges Template",
                tax_template=None,  # Pass None here to get default taxes
                company=company
            )
            
            # If tax details are returned, set the taxes in your invoice
            if tax_details and "taxes" in tax_details:
                for tax in tax_details["taxes"]:
                    tax["cost_center"] = cost_center
                    sales_invoice_doc.append("taxes", tax)

    current_date = getdate(today())
    site_name=customer_details.site_name
    contract_end_date = get_contract_end_date(site_name)

    existing_paid_invoices = frappe.get_all("Sales Invoice",
        filters={"subscription": subscription, "status": "Paid"},
        fields=["name", "from_date", "to_date"],
        order_by="creation DESC"
    )
    
    if existing_paid_invoices:
        latest_to_date = getdate(existing_paid_invoices[0].to_date)
        from_date = latest_to_date + timedelta(days=1)
        if current_date > from_date:
            from_date = current_date
    else:
        from_date = current_date

    has_time = True
    if current_date == from_date:
        current_day_name = current_date.strftime("%A")
        is_wash_day = any(day.day == current_day_name for day in subscription.custom_subscription_day_and_time)
        
        if is_wash_day:
            wash_time = next((day.time for day in subscription.custom_subscription_day_and_time 
                            if day.day == current_day_name), None)
            has_time = has_sufficient_time(site_name, frappe.utils.nowtime(), wash_time)
            if not has_time:
                from_date = find_next_service_day(subscription, current_date)

    if from_date > contract_end_date:
        frappe.throw(f"Cannot generate invoice as the contract ended on {contract_end_date}")

    billing_days = get_billing_interval_details(subscription, from_date)
    to_date = from_date + timedelta(days=billing_days)

    # from_date = getdate(subscription.start_date)
    # billing_days = get_billing_interval_details(subscription, from_date)
    # if not billing_days:
    #     frappe.throw("Could not determine billing interval")
    # to_date = from_date + timedelta(days=billing_days)

    # Fetch the subscription plan rate
    subscription_plan = frappe.get_doc("Subscription Plan", package_id)
    # Paid through a payment link (card): income is booked directly, not deferred
    item = {
        'doctype': 'Sales Invoice Item',
        'item_code': subscription_plan.item,
        'qty': 1,
        'rate': subscription_plan.cost,
        "enable_deferred_revenue": 0,
        "income_account": get_income_account(sales_invoice_doc.company),
        "cost_center" : cost_center
    }
    sales_invoice_doc.append('items', item)
    
    # Insert and save the Sales Invoice
    sales_invoice_doc.insert(ignore_permissions=True)
    sales_invoice_doc.save(ignore_permissions=True)
    invoice_id=sales_invoice_doc.name

    # Generate order ID for payment
    order_number = generating_the_order_no_for_payment(whatsapp_id, customer_details.site_name)
    # Assign custom order ID to the sales invoice
    sales_invoice_doc.custom_order_id = order_number

    # Create a Customer Vehicle Order
    creating_new_customer_vehicle_order(order_number, whatsapp_id)

    site_config = frappe.get_site_config()
    merchant_pass_id = site_config.get("merchant_password")
    getting_plan_rate = frappe.get_doc("Subscription Plan", package_id, fields=["cost", "currency"])
    # need to make the amount format as 09.00 not 09.0
    order_amount_hash = "{:.2f}".format(sales_invoice_doc.rounded_total or sales_invoice_doc.grand_total)
    order_currency_hash = getting_plan_rate.currency
    order_description_hash = package_id
    # Creating a hash for payment redirect url
    generated_hashing_value = generating_the_hash_for_payment_authentication(
        order_number, 
        order_amount_hash,
        order_currency_hash, 
        order_description_hash, 
        merchant_pass_id
    )

    # Payment Authentication
    whatsapp_contact_id = whatsapp_id
    first_name = customer_details.first_name
    last_name = customer_details.last_name
    if payment_type=="Recurring Payment":
        req_token_boolean = True
        recurring_init_boolean = True
    else:
        req_token_boolean = False
        recurring_init_boolean = False

    # frappe.log_error("Payment Type", methods)
    # frappe.log_error("req_token_boolean",req_token_boolean)
    # frappe.log_error("recurring_init_boolean",recurring_init_boolean)
    # Payment redirect url
    payment_redirect_url = authentication_of_payment_request(
        order_number, 
        order_amount_hash, 
        order_currency_hash, 
        order_description_hash, 
        whatsapp_contact_id, 
        first_name, 
        last_name,
        generated_hashing_value, 
        req_token_boolean, 
        recurring_init_boolean,
        customer_details,
        payment_type,
        invoice_id
    )

    # Insert and save the Sales Invoice
    # sales_invoice_doc.insert(ignore_permissions=True)
    sales_invoice_doc.save(ignore_permissions=True)
    # frappe.db.commit()

    return payment_redirect_url, order_number



def generating_the_order_no_for_payment(whatsapp_contact_id, site_name):
    """
    Generates unique order number using WhatsApp ID and site details.
    
    Returns:
        str: Formatted order number
    """
    last_four_digits = whatsapp_contact_id[-5:]
    random_suffix = ''.join(random.choices('0123456789', k=15))
    formatted_site_name = (site_name.lower()).replace(" ", "-")
    sales_invoice_field_values = f"Trie-{formatted_site_name}-{last_four_digits}-{random_suffix}"
    return sales_invoice_field_values


def generating_the_hash_for_payment_authentication(order_number_hash, order_amount_hash, order_currency_hash, order_description_hash, merchant_pass_hash):
    """
    Generates secure hash for payment authentication.
    
    Returns:
        str: SHA1 hash of payment details
    """
    order_amount_hash = str(order_amount_hash)
    data = (order_number_hash + order_amount_hash + order_currency_hash + order_description_hash + merchant_pass_hash).upper()
    md5_hash = hashlib.md5(data.encode()).hexdigest()
    sha1_hash = hashlib.sha1(md5_hash.encode()).hexdigest()
    return sha1_hash


def authentication_of_payment_request(order_number_hash, order_amount_hash, order_currency_hash, order_description_hash, whatsapp_contact_id, first_name, last_name, generated_hashing_value, req_token_boolean, recurring_init_boolean, doc,payment_type,invoice_id):
    """
    Handles payment gateway authentication and creates payment session.
    
    Returns:
        dict: Payment gateway response with redirect URL
    """
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
    # methods = ["card", "applepay"]
    methods = ["card"] if recurring_init_boolean else ["card", "applepay"]
    # frappe.log_error("Payment Methods", f"Methods: {methods}, Recurring: {recurring_init_boolean}, Type: {payment_type}")
    
    url = f"{global_totalpay_url}/api/v1/session"
    payload = {
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
      "hash": generated_hashing_value
    }
    if payment_type=="One Time Payment":
        custom_data = {"one_time_payment": "True", "invoice_no": invoice_id}
        payload["custom_data"] = custom_data
    payload = json.dumps(payload)
    headers = {
      'Content-Type': 'application/json'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    json_response = frappe.utils.data.json.loads(response.text)
    log_operational(json_response, "Payment Response")

    return json_response


def creating_new_customer_vehicle_order(order_number, whatsapp_id):
    """
    Creates new vehicle order record for customer.
    
    Args:
        order_number (str): Unique order identifier
        whatsapp_id (str): Customer's WhatsApp number
    """
    # Get customer details and create vehicle order
    getting_whatsapp_customer_doc = frappe.get_doc("WhatsApp Customer Details", whatsapp_id)

    if getting_whatsapp_customer_doc:
        new_doc = frappe.new_doc("Customer Vehicle Order")
        new_doc.order_id = order_number
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