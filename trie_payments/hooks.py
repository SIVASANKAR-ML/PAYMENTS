app_name = "trie_payments"
app_title = "Trie Payments"
app_publisher = "Tridz"
app_description = "The Trie Payment App offers secure, instant payments and expense tracking with a user-friendly interface, making financial management simple and efficient."
app_email = "trie@gmail.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/trie_payments/css/trie_payments.css"
# app_include_js = "/assets/trie_payments/js/trie_payments.js"

# include js, css files in header of web template
# web_include_css = "/assets/trie_payments/css/trie_payments.css"
# web_include_js = "/assets/trie_payments/js/trie_payments.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "trie_payments/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "trie_payments.utils.jinja_methods",
# 	"filters": "trie_payments.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "trie_payments.install.before_install"
# after_install = "trie_payments.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "trie_payments.uninstall.before_uninstall"
# after_uninstall = "trie_payments.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "trie_payments.utils.before_app_install"
# after_app_install = "trie_payments.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "trie_payments.utils.before_app_uninstall"
# after_app_uninstall = "trie_payments.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "trie_payments.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

fixtures = ["Custom Field","Client Script"]

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
    "Subscription Action" : {
        "validate" : "trie_payments.hook_functions.unpaid_subscription",
	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"trie_payments.tasks.all"
# 	],
# 	"daily": [
# 		"trie_payments.tasks.daily"
# 	],
# 	"hourly": [
# 		"trie_payments.tasks.hourly"
# 	],
# 	"weekly": [
# 		"trie_payments.tasks.weekly"
# 	],
# 	"monthly": [
# 		"trie_payments.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "trie_payments.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "trie_payments.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "trie_payments.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["trie_payments.utils.before_request"]
# after_request = ["trie_payments.utils.after_request"]

# Job Events
# ----------
# before_job = ["trie_payments.utils.before_job"]
# after_job = ["trie_payments.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"trie_payments.auth.validate"
# ]
