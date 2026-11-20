from django import forms

from .models import UserInteraction


class HistoryFilterForm(forms.Form):
    event = forms.ChoiceField(
        label="Hoạt động",
        required=False,
        choices=[("", "Tất cả hoạt động"), *UserInteraction.Event.choices],
    )


class ReviewForm(forms.Form):
    rating = forms.TypedChoiceField(
        label="Chọn mức đánh giá",
        choices=[(i, f"{i} sao") for i in range(1, 6)],
        coerce=int,
        widget=forms.RadioSelect,
    )
    comment = forms.CharField(
        label="Nhận xét của bạn",
        max_length=3000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
