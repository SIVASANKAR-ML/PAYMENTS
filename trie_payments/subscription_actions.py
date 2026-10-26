import frappe, json
import requests
from .external_form_payment_functions import scheduler_info, generating_the_hash_id_for_subscription

def updating_subscription_scheduler(scheduler_id, update_type, update_value):
    """
    Updates an existing subscription scheduler with new date or amount
    
    Args:
        scheduler_id: Unique identifier for the scheduler
        update_type: Either "UPDATE_DATE" or "UPDATE_AMOUNT"
        update_value: New date or amount value depending on update_type
    
    Returns:
        dict: Success response with updated scheduler details
        str: "failed" if operation fails
    """
    if not scheduler_id:
        frappe.log_error(f"updating_subscription_scheduler called with empty scheduler_id. update_type={update_type}", "Scheduler Update Skipped")
        return "failed"
    # Generate hash ID for security validation
    generated_hash_id = generating_the_hash_id_for_subscription(scheduler_id)
    
    # Get current scheduler information
    scheduler_info_values = scheduler_info(scheduler_id, generated_hash_id)
    scheduler_values = json.loads(scheduler_info_values)
    
    # Handle different update types
    match update_type:
        case "UPDATE_DATE":
            amount = scheduler_values.get("amount")  # Keep existing amount
            date = update_value  # Update date
        case "UPDATE_AMOUNT":
            amount = update_value  # Update amount
            date = scheduler_values.get("next_execute")  # Keep existing date
        case _:
            raise ValueError(f"Invalid update type: {update_type}")
    
    try:
        # Call scheduler action with updated values
        response = scheduler_action(scheduler_id, date, amount, generated_hash_id)
        parsing_response = json.loads(response)
        
        # Format the response
        response = {
            "scheduler_id": parsing_response.get("schedule_id"),
            "name": parsing_response.get("name"),
            "interval_length": parsing_response.get("interval_length"),
            "interval_unit": parsing_response.get("interval_unit"),
            "amount": parsing_response.get("amount"),
            "next_execute": parsing_response.get("next_execute"),
            "status": "success"
        }
        return response
    except Exception as e:
        frappe.log_error("PG Update ", e)
        return "failed"
    
def update_scheduler_date_and_amount(scheduler_id, date, amount):
    """
    Update scheduler date and amount in a single API call.
    Does NOT call scheduler_info — caller provides both values directly.
    """
    if not scheduler_id:
        frappe.log_error(f"update_scheduler_date_and_amount called with empty scheduler_id", "Scheduler Update Skipped")
        return "failed"
    
    generated_hash_id = generating_the_hash_id_for_subscription(scheduler_id)
    
    try:
        response = scheduler_action(scheduler_id, date, amount, generated_hash_id)
        parsing_response = json.loads(response)
        return {
            "scheduler_id": parsing_response.get("schedule_id"),
            "next_execute": parsing_response.get("next_execute"),
            "amount": parsing_response.get("amount"),
            "status": "success"
        }
    except Exception as e:
        frappe.log_error(f"Failed to update scheduler {scheduler_id}: {str(e)}", "Scheduler Update Failed")
        return "failed"


def scheduler_action(schedule_id, end_date, amount, generated_hash_id):
    """
    Makes an API call to update the scheduler
    
    Args:
        schedule_id: Unique identifier for the scheduler
        end_date: New execution date
        amount: Updated amount
        generated_hash_id: Security hash for validation
    
    Returns:
        str: API response text or "error" if request fails
    """
    # Get configuration from site settings
    site_config = frappe.get_site_config()
    scheduler_url = site_config.get("scheduler_url")
    merchant_id = site_config.get("merchant_id")  # Note: Duplicate line in original code
    merchant_key = site_config.get("merchant_key")

    try:
        url = f"{scheduler_url}/post"
        # Prepare payload for API request
        payload = {
            'action': 'UPDATE_SCHEDULE',
            'merchant_id': f'{merchant_id}',
            'client_key': f'{merchant_key}',
            'schedule_id': f'{schedule_id}',
            'next_execute': f'{end_date}',
            'hash': f'{generated_hash_id}',
            'amount': f'{amount}'
        }
        
        response = requests.request("POST", url, headers={}, data=payload)
        return response.text
    
    except Exception as e:
        frappe.log_error("Error pausing or cancelling the scheduler", e)
        return "error"
    
def cancel_payment_scheduler(scheduler_id):
    """
    Cancel a TotalPay schedule via DELETE_SCHEDULE so it stops billing entirely.
    Confirmed against TotalPay's docs (docs.totalpay.global/docs/guides/s2s_card#delete-schedule-request).
    """
    if not scheduler_id:
        return "failed"

    generated_hash_id = generating_the_hash_id_for_subscription(scheduler_id)
    site_config = frappe.get_site_config()
    scheduler_url = site_config.get("scheduler_url")
    merchant_id = site_config.get("merchant_id")
    merchant_key = site_config.get("merchant_key")

    try:
        url = f"{scheduler_url}/post"
        payload = {
            'action': 'DELETE_SCHEDULE',
            'merchant_id': f'{merchant_id}',
            'client_key': f'{merchant_key}',
            'schedule_id': f'{scheduler_id}',
            'hash': generated_hash_id,
        }
        response = requests.request("POST", url, headers={}, data=payload)
        result = json.loads(response.text)
        return "success" if result.get("result") == "SUCCESS" else "failed"
    except Exception as e:
        frappe.log_error(f"Error cancelling scheduler {scheduler_id}: {str(e)}", "Scheduler Cancellation Failed")
        return "failed"