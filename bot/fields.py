# bot/fields.py

import json
from django.db import models

class ListaHorariosField(models.TextField):
    def from_db_value(self, value, expression, connection):
        if value is None:
            return []
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []

    def to_python(self, value):
        if isinstance(value, list):
            return value
        if value is None:
            return []
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []

    def get_prep_value(self, value):
        if isinstance(value, list):
            return json.dumps(value)
        return value
