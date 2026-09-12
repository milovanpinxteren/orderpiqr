from django.apps import apps
from django.contrib import admin, messages
from django.contrib.admin.helpers import AdminForm
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .forms import HashedTokenAdminForm
from .models import HashedToken

apps.get_app_config('drf_hashed_token').verbose_name = _("Hashed auth tokens")


@admin.register(HashedToken)
class HashedTokenAdmin(admin.ModelAdmin):
    form = HashedTokenAdminForm
    readonly_fields = ("created", "show_token")
    list_display = ("user", "stage", "created")
    list_select_related = ("user",)

    def show_token(self, obj):
        key = getattr(obj, "_raw_token", False)
        if key:
            return format_html(
                '''
                <input type="text" value="{}" id="token" readonly />
                <button type="button" class="button" onclick="copyTokenToClipboard('token', this)">Copy</button>
                <span class="copy-feedback" style="margin-left: 10px;"></span>
                ''',
                key
            )
        return "-"

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        form = context["adminform"].form
        if hasattr(obj, "_raw_token") and "show_token" in form.fields:
            form.fields["show_token"].initial = obj._raw_token
        return super().render_change_form(request, context, add, change, form_url, obj)

    def response_add(self, request, obj, post_url_continue=None):
        obj._raw_token = getattr(obj, "_raw_token", None)
        self.message_user(request, "Token successfully created. Copy and store it now — it will not be shown again.", messages.SUCCESS)

        ModelForm = self.get_form(request)
        form = ModelForm(instance=obj)

        admin_form = AdminForm(
            form,
            list(self.get_fieldsets(request)),
            self.get_prepopulated_fields(request),
            self.get_readonly_fields(request, obj),
            model_admin=self,
        )

        context = {
            **self.admin_site.each_context(request),
            "adminform": admin_form,
            "object_id": obj.pk,
            "original": obj,
            "is_popup": False,
            "media": self.media + form.media,
            "errors": form.errors,
            "app_label": self.model._meta.app_label,
            "opts": self.model._meta,
            "change": False,
            "add": False,
            "has_view_permission": self.has_view_permission(request, obj),
            "has_add_permission": self.has_add_permission(request),
            "has_change_permission": self.has_change_permission(request, obj),
            "has_delete_permission": self.has_delete_permission(request, obj),
            "save_as": False,
            "show_save": True,
            "show_save_and_continue": False,
            "show_save_and_add_another": False,
            "inline_admin_formsets": ()
        }

        return self.render_change_form(
            request=request,
            context=context,
            add=False,
            change=False,
            form_url="",
            obj=obj,
        )

    def has_change_permission(self, request, obj=None):
        return False if obj else True

    class Media:
        js = ['drf_hashed_token/copy_token.js']
