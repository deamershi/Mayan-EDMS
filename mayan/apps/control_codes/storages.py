from __future__ import unicode_literals

from mayan.apps.storage.utils import get_storage_subclass

from .settings import (
    setting_control_sheet_code_image_cache_storage,
    setting_control_sheet_code_image_storage_arguments
)

storage_controlsheetcodeimagecache = get_storage_subclass(
    dotted_path=setting_control_sheet_code_image_cache_storage.value
)(**setting_control_sheet_code_image_storage_arguments.value)