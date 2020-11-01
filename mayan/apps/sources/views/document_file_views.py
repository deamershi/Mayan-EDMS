import logging

from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _

from mayan.apps.acls.models import AccessControlList
from mayan.apps.documents.literals import DOCUMENT_FILE_ACTION_PAGES_NEW
from mayan.apps.documents.models import Document, DocumentFile
from mayan.apps.documents.permissions import permission_document_file_new
from mayan.apps.documents.tasks import task_document_file_upload
from mayan.apps.storage.models import SharedUploadedFile

from ..exceptions import SourceException
from ..forms import NewFileForm

from .base import UploadBaseView

__all__ = ('DocumentFileUploadInteractiveView',)
logger = logging.getLogger(name=__name__)


class DocumentFileUploadInteractiveView(UploadBaseView):
    def dispatch(self, request, *args, **kwargs):
        self.subtemplates_list = []

        self.document = get_object_or_404(
            klass=Document, pk=kwargs['document_id']
        )

        AccessControlList.objects.check_access(
            obj=self.document, permissions=(permission_document_file_new,),
            user=self.request.user
        )

        try:
            DocumentFile.execute_pre_create_hooks(
                kwargs={
                    'document': self.document,
                    'shared_uploaded_file': None,
                    'user': self.request.user
                }
            )
        except Exception as exception:
            messages.error(
                message=_(
                    'Unable to upload new files for document '
                    '"%(document)s". %(exception)s'
                ) % {'document': self.document, 'exception': exception},
                request=self.request
            )
            return HttpResponseRedirect(
                redirect_to=reverse(
                    viewname='documents:document_file_list',
                    kwargs={'document_id': self.document.pk}
                )
            )

        self.tab_links = UploadBaseView.get_active_tab_links(
            document=self.document
        )

        return super().dispatch(request, *args, **kwargs)

    def forms_valid(self, forms):
        try:
            uploaded_file = self.source.get_backend_instance().get_upload_file_object(
                form_data=forms['source_form'].cleaned_data
            )
        except SourceException as exception:
            messages.error(message=exception, request=self.request)
        else:
            shared_uploaded_file = SharedUploadedFile.objects.create(
                file=uploaded_file.file
            )

            try:
                self.source.clean_up_upload_file(uploaded_file)
            except Exception as exception:
                messages.error(message=exception, request=self.request)

            if not self.request.user.is_anonymous:
                user = self.request.user
                user_id = self.request.user.pk
            else:
                user = None
                user_id = None

            try:
                DocumentFile.execute_pre_create_hooks(
                    kwargs={
                        'document': self.document,
                        'shared_uploaded_file': shared_uploaded_file,
                        'user': user
                    }
                )

                task_document_file_upload.apply_async(
                    kwargs={
                        'action': int(
                            forms['document_form'].cleaned_data.get('action')
                        ),
                        'comment': forms['document_form'].cleaned_data.get('comment'),
                        'document_id': self.document.pk,
                        'shared_uploaded_file_id': shared_uploaded_file.pk,
                        'user_id': user_id
                    }
                )
            except Exception as exception:
                message = _(
                    'Error executing document file upload task; '
                    '%(exception)s'
                ) % {
                    'exception': exception,
                }
                logger.critical(msg=message, exc_info=True)
                if self.request.is_ajax():
                    return JsonResponse(
                        data={'error': force_text(s=message)}, status=500
                    )
                else:
                    raise type(exception)(message)
            else:
                messages.success(
                    message=_(
                        'New document file queued for upload and will be '
                        'available shortly.'
                    ), request=self.request
                )

        return HttpResponseRedirect(
            redirect_to=reverse(
                viewname='documents:document_file_list', kwargs={
                    'document_id': self.document.pk
                }
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                'form_action': '{}?{}'.format(
                    reverse(
                        viewname=self.request.resolver_match.view_name,
                        kwargs=self.request.resolver_match.kwargs
                    ), self.request.META['QUERY_STRING']
                ),
                'object': self.document,
                'title': _(
                    'Upload a new file for document "%(document)s" '
                    'from source: %(source)s'
                ) % {'document': self.document, 'source': self.source.label},
                'submit_label': _('Submit')
            }
        )

        context.update(
            self.source.get_backend_instance().get_view_context(
                context=context, request=self.request
            )
        )

        return context

    def get_form_classes(self):
        return {
            'document_form': NewFileForm,
            'source_form': self.source.get_backend().upload_form_class
        }

    def get_form_extra_kwargs__source_form(self, **kwargs):
        return {
            'source': self.source,
        }

    def get_initial__document_form(self):
        return {'action': DOCUMENT_FILE_ACTION_PAGES_NEW}
