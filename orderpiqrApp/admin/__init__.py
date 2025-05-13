from .device_admin import *
from .picklist_admin import *
from .product_admin import *
from .customer_admin import *
from .userprofile_admin import *

#
# from django.contrib import admin
# from django.contrib.auth.models import User
# from django.contrib.auth.models import Group
#
#
# def unregister_user_model_for_companyadmins():
#     """Unregister the User model for companyadmins only."""
#     # Check if the current user is a companyadmin
#     from django.contrib.auth import get_user_model
#     if admin.site.is_registered(User):
#         if get_user_model().objects.filter(groups__name='companyadmin').exists():
#             admin.site.unregister(User)
#
# # Call the function to unregister the User model for companyadmins
# unregister_user_model_for_companyadmins()