from django import forms

from .models import HashedToken


class HashedTokenAdminForm(forms.ModelForm):
    show_token = forms.CharField(
        label="Generated Token (only visible once)",
        required=False,
        widget=forms.TextInput(attrs={
            "readonly": "readonly",
            "id": "id_show_token",
            "style": "width:80%;display:inline-block;margin-right:10px;"
        })
    )

    class Meta:
        model = HashedToken
        fields = ["user", "stage"]

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw_token, key_hash = HashedToken.generate_token()
        instance.key_hash = key_hash
        instance._raw_token = f"{instance.get_stage_display()}_{raw_token}"
        if commit:
            instance.save()
        self.cleaned_data["show_token"] = instance._raw_token
        return instance
