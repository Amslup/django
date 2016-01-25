from __future__ import unicode_literals

from django.contrib.admin import helpers
from django.contrib.admin.exceptions import DisallowedModelAdminToField
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.forms.formsets import all_valid
from django.http import Http404
from django.utils.encoding import force_text
from django.utils.html import escape
from django.utils.translation import ugettext as _
from django.views.generic import View

IS_POPUP_VAR = '_popup'
TO_FIELD_VAR = '_to_field'


class ChangeFormView(View):
    admin = None
    object_id = None
    form_url = ''
    extra_context = None

    def __init__(self, admin, object_id=None, form_url='', extra_context=None, **kwargs):
        super(ChangeFormView, self).__init__(**kwargs)
        self.admin = admin
        self.object_id = object_id
        self.form_url = form_url
        self.extra_context = extra_context or {}
        self.obj = None

    def _get_object(self, request):
        if self.object_id is None:
            return None
        self.obj = self.obj or self.admin.get_object(request, unquote(self.object_id), self._to_field(request))
        return self.obj

    def _to_field(self, request):
        return request.POST.get(TO_FIELD_VAR, request.GET.get(TO_FIELD_VAR))

    def _check_field_can_be_referenced(self, request):
        to_field = self._to_field(request)
        if to_field and not self.admin.to_field_allowed(request, to_field):
            raise DisallowedModelAdminToField("The field %s cannot be referenced." % to_field)

    def _get_form(self, request):
        return self.admin.get_form(request, self._get_object(request))

    def dispatch(self, request, *args, **kwargs):
        self._check_field_can_be_referenced(request)
        self._check_permissions(request)
        return super(ChangeFormView, self).dispatch(request, *args, **kwargs)

    def _log_and_response(self):
        raise NotImplementedError

    def post(self, request, *args, **kwargs):
        add = self.object_id is None
        ModelForm = self._get_form(request)
        obj_instance = self._get_object(request) if '_saveasnew' not in request.POST else None
        form = ModelForm(request.POST, request.FILES, instance=obj_instance)
        form_validated, new_object = form.validate_and_save(request, change=not add)
        formsets, inline_instances = self.admin._create_formsets(request, new_object, change=not add)
        if all_valid(formsets) and form_validated:
            return self._log_and_response(request, new_object, form, formsets)

        form_validated = False
        # Hide the "Save" and "Save and continue" buttons if "Save as New" was
        # previously chosen to prevent the interface from getting confusing.
        if "_saveasnew" in request.POST:
            self.extra_context['show_save'] = False
            self.extra_context['show_save_and_continue'] = False
        return self.render_form(
            request, form, form_validated, formsets, inline_instances, initial=None, **kwargs)

    def get_context(self, request, form, form_validated, formsets, inline_instances, initial=None, **kwargs):
        obj = self._get_object(request)
        adminForm = helpers.AdminForm(
            form,
            list(self.admin.get_fieldsets(request, obj)),
            self.admin.get_prepopulated_fields(request, obj),
            self.admin.get_readonly_fields(request, obj),
            model_admin=self.admin)
        media = self.admin.media + adminForm.media
        inline_formsets = self.admin.get_inline_formsets(request, formsets, inline_instances, obj)
        for inline_formset in inline_formsets:
            media = media + inline_formset.media
        context = dict(
            self.admin.admin_site.each_context(request),
            adminform=adminForm,
            object_id=self.object_id,
            original=self._get_object(request),
            is_popup=(IS_POPUP_VAR in request.POST or
                      IS_POPUP_VAR in request.GET),
            to_field=self._to_field(request),
            media=media,
            inline_admin_formsets=inline_formsets,
            errors=helpers.AdminErrorList(form, formsets),
            preserved_filters=self.admin.get_preserved_filters(request),
        )
        context.update(self.extra_context)
        return context

    @property
    def _form_action_callback(self):
        raise NotImplementedError

    def render_form(self, request, form, form_validated, formsets, inline_instances,
                    initial=None, **kwargs):
        context = self.get_context(
            request, form, form_validated, formsets, inline_instances, initial=initial, **kwargs)
        obj = self._get_object(request)
        return self._form_action_callback(
            request, context, obj=obj, form_url=self.form_url)


class ChangeView(ChangeFormView):
    def _check_permissions(self, request):
        obj = self._get_object(request)
        if not self.admin.has_change_permission(request, obj):
            raise PermissionDenied
        if obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {
                'name': force_text(self.admin.model._meta.verbose_name), 'key': escape(self.object_id)})

    def get(self, request, **kwargs):
        obj = self._get_object(request)
        form = self._get_form(request)(instance=obj)
        formsets, inline_instances = self.admin._create_formsets(request, obj, change=True)
        form_validated = False
        return self.render_form(
            request, form, form_validated, formsets, inline_instances, initial=None, **kwargs)

    def _log_and_response(self, request, new_object, form, formsets):
        self.admin.save_model(request, new_object, form, True)
        self.admin.save_related(request, form, formsets, True)
        change_message = self.admin.construct_change_message(request, form, formsets, False)
        self.admin.log_change(request, new_object, change_message)
        return self.admin.response_change(request, new_object)

    def get_context(self, request, form, form_validated, formsets, inline_instances, initial=None, **kwargs):
        context = super(ChangeView, self).get_context(
            request, form, form_validated, formsets, inline_instances, initial=initial, **kwargs)
        context.update({
            'title': _('Change %s') % force_text(self.admin.model._meta.verbose_name)
        })
        return context

    @property
    def _form_action_callback(self):
        return self.admin.render_change_form


class AddView(ChangeFormView):
    def _check_permissions(self, request):
        if not self.admin.has_add_permission(request):
            raise PermissionDenied

    def _log_and_response(self, request, new_object, form, formsets):
        self.admin.save_model(request, new_object, form, False)
        self.admin.save_related(request, form, formsets, False)
        change_message = self.admin.construct_change_message(request, form, formsets, True)
        self.admin.log_addition(request, new_object, change_message)
        return self.admin.response_add(request, new_object)

    def get(self, request, **kwargs):
        initial = self.admin.get_changeform_initial_data(request)
        form = self._get_form(request)(initial=initial)
        formsets, inline_instances = self.admin._create_formsets(request, form.instance, change=False)
        form_validated = False
        return self.render_form(
            request, form, form_validated, formsets, inline_instances, initial=initial, **kwargs)

    def get_context(self, request, form, form_validated, formsets, inline_instances, initial=None, **kwargs):
        context = super(AddView, self).get_context(
            request, form, form_validated, formsets, inline_instances, initial=initial, **kwargs)
        context.update({
            'title': _('Add %s') % force_text(self.admin.model._meta.verbose_name)
        })
        return context

    @property
    def _form_action_callback(self):
        return self.admin.render_add_form
