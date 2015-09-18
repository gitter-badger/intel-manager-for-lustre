#
# INTEL CONFIDENTIAL
#
# Copyright 2013-2015 Intel Corporation All Rights Reserved.
#
# The source code contained or described herein and all documents related
# to the source code ("Material") are owned by Intel Corporation or its
# suppliers or licensors. Title to the Material remains with Intel Corporation
# or its suppliers and licensors. The Material contains trade secrets and
# proprietary and confidential information of Intel or its suppliers and
# licensors. The Material is protected by worldwide copyright and trade secret
# laws and treaty provisions. No part of the Material may be used, copied,
# reproduced, modified, published, uploaded, posted, transmitted, distributed,
# or disclosed in any way without Intel's prior express written permission.
#
# No license under any patent, copyright, trade secret or other intellectual
# property right is granted to or conferred upon you by disclosure or delivery
# of the Materials, either expressly, by implication, inducement, estoppel or
# otherwise. Any license under such intellectual property rights must be
# express and approved by Intel in writing.


import logging

from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.generic import GenericForeignKey
from django.utils import timezone
from django.db import IntegrityError

from chroma_core.models.sparse_model import SparseModel
from chroma_core.models import utils as conversion_util
from chroma_core.lib.job import job_log


class AlertStateBase(SparseModel):
    class Meta:
        abstract = True
        unique_together = ('alert_item_type', 'alert_item_id', 'alert_type', 'active')
        ordering = ['id']
        app_label = 'chroma_core'

    table_name = 'chroma_core_alertstate'
    """Records a period of time during which a particular
       issue affected a particular element of the system"""
    alert_item_type = models.ForeignKey(ContentType)
    alert_item_id = models.PositiveIntegerField()
    # FIXME: generic foreign key does not automatically set up deletion
    # of this when the alert_item is deleted -- do it manually
    alert_item = GenericForeignKey('alert_item_type', 'alert_item_id')

    alert_type = models.CharField(max_length = 128)

    begin = models.DateTimeField(help_text = "Time at which the alert started",
                                 default=timezone.now)
    end = models.DateTimeField(help_text = "Time at which the alert was resolved\
            if active is false, else time that the alert was last checked (e.g.\
            time when we last checked an offline target was still not offline)",
                               null=True)

    # Note: use True and None instead of True and False so that
    # unique-together constraint only applied to active alerts
    active = models.NullBooleanField()

    # whether a user has manually dismissed alert
    dismissed = models.BooleanField(default=False,
                                    help_text = "True denotes that the user "
                                                "has acknowledged this alert.")

    severity = models.IntegerField(default=logging.INFO,
                                   help_text = ("String indicating the "
                                                "severity of the alert, "
                                                "one of %s") %
                                        conversion_util.STR_TO_SEVERITY.keys())

    # This is only used by one event ClientConnectEvent but it is critical and so needs to be searchable etc
    # for that reason it can't use the variant
    lustre_pid = models.IntegerField(null = True)

    # Subclasses set this, used as a default in .notify()
    default_severity = logging.INFO

    # For historical compatibility anything called Alert will send and alert email and anything else won't.
    # This can obviously be overridden by any particular event but gives us a like for behavour.
    @property
    def require_mail_alert(self):
        return "Alert\'>" in str(type(self))

    def get_active_bool(self):
        return bool(self.active)

    def set_active_bool(self, value):
        if value:
            self.active = True
        else:
            self.active = None

    active_bool = property(get_active_bool, set_active_bool)

    @property
    def affected_objects(self):
        """
        :return: A list of objects other than the alert_item that are affected by this alert
        """
        return []

    def end_event(self):
        return None

    def message(self):
        raise NotImplementedError()

    def affected_targets(self, affect_target):
        pass

    @classmethod
    def subclasses(cls):
        all_subclasses = []
        for subclass in cls.__subclasses__():
            all_subclasses.append(subclass)
            all_subclasses.extend(subclass.subclasses())
        return all_subclasses

    @classmethod
    def filter_by_item(cls, item):
        if hasattr(item, 'content_type'):
            # A DowncastMetaclass object
            return cls.objects.filter(active = True,
                    alert_item_id = item.id,
                    alert_item_type = item.content_type)
        else:
            return cls.objects.filter(active = True,
                    alert_item_id = item.pk,
                    alert_item_type__model = item.__class__.__name__.lower(),
                    alert_item_type__app_label = item.__class__._meta.app_label)

    @classmethod
    def filter_by_item_id(cls, item_class, item_id):
        return cls.objects.filter(active = True,
                alert_item_id = item_id,
                alert_item_type__model = item_class.__name__.lower(),
                alert_item_type__app_label = item_class._meta.app_label)

    @classmethod
    def notify(cls, alert_item, active, **kwargs):
        """Notify an alert in the default severity level for that alert"""

        return cls._notify(alert_item, active, **kwargs)

    @classmethod
    def notify_warning(cls, alert_item, active, **kwargs):
        """Notify an alert in at most the WARNING severity level"""

        kwargs['attrs_to_save'] = {'severity': min(
            cls.default_severity, logging.WARNING)}
        return cls._notify(alert_item, active, **kwargs)

    @classmethod
    def _notify(cls, alert_item, active, **kwargs):
        if hasattr(alert_item, 'content_type'):
            alert_item = alert_item.downcast()

        if active:
            return cls.high(alert_item, **kwargs)
        else:
            return cls.low(alert_item, **kwargs)

    @classmethod
    def _get_attrs_to_save(cls, kwargs):
        # Prepare data to be saved with alert, but not effect the filter_by_item() below
        # e.g. Only one alert type per alert item can be active, so we don't need to filter on severity.
        attrs_to_save = kwargs.pop('attrs_to_save', {})

        # Add any properties to the attrs_to_save that are not db fields, we can't search on
        # non db fields after all. Some alerts have custom fields and they will be searched out here.
        fields = [field.attname for field in cls._meta.fields]
        for attr in kwargs.keys():
            if attr not in fields:
                attrs_to_save[attr] = kwargs.pop(attr)

        return attrs_to_save

    @classmethod
    def high(cls, alert_item, **kwargs):
        if hasattr(alert_item, 'not_deleted') and alert_item.not_deleted != True:
            return None

        attrs_to_save = cls._get_attrs_to_save(kwargs)

        try:
            alert_state = cls.filter_by_item(alert_item).get(**kwargs)
        except cls.DoesNotExist:
            kwargs.update(attrs_to_save)

            if not 'alert_type' in kwargs:
                kwargs['alert_type'] = cls.__name__
            if not 'severity' in kwargs:
                kwargs['severity'] = cls.default_severity

            alert_state = cls(active = True,
                              dismissed = False,  # Users dismiss, not the software
                              alert_item = alert_item,
                              **kwargs)
            try:
                alert_state.save()
                job_log.info("AlertState: Raised %s on %s "
                             "at severity %s" % (cls,
                                                 alert_state.alert_item,
                                                 alert_state.severity))
            except IntegrityError, e:
                job_log.warning("AlertState: IntegrityError %s saving %s : %s : %s" % (e, cls.__name__, alert_item, kwargs))
                # Handle colliding inserts: drop out here, no need to update
                # the .end of the existing record as we are logically concurrent
                # with the creator.
                return None
        return alert_state

    @classmethod
    def low(cls, alert_item, **kwargs):
        # currently, no attrs are saved when an attr is lowered, so just filter them out of kwargs
        cls._get_attrs_to_save(kwargs)

        try:
            alert_state = cls.filter_by_item(alert_item).get(**kwargs)
            alert_state.end = timezone.now()
            alert_state.active = None
            alert_state.save()

            # We optionally emit an event when alerts are lowered: we don't do that
            # for the beginning because that is implicit in the alert itself, whereas
            # the end can reasonably have a different message.
            ee = alert_state.end_event()
            if ee:
                ee.save()
        except cls.DoesNotExist:
            alert_state = None

        return alert_state

    @classmethod
    def register_event(cls, alert_item, **kwargs):
        # Events are Alerts with no duration, so just go high/low.
        cls.high(alert_item, attrs_to_save=kwargs)
        cls.low(alert_item, attrs_to_save=kwargs)

    def cast(self, target_class):
        """
        Works exactly as the super except because we duplicate record_type with alert_type. We should remove in the
        future, but for now this fixes that up.
        :param target_class:
        :return:
        """
        # If the save fails for some reason then this change will have no affect.
        self.alert_type = target_class._meta.object_name

        return super(AlertStateBase, self).cast(target_class)


class AlertState(AlertStateBase):
    # This is worse than INFO because it *could* indicate that
    # a filesystem is unavailable, but it is not necessarily
    # so:
    # * Host can lose contact with us but still be servicing clients
    # * Host can be offline entirely but filesystem remains available
    #   if failover servers are available.
    default_severity = logging.WARNING

    is_sparse_base = True

    class Meta:
        app_label = 'chroma_core'
        db_table = AlertStateBase.table_name


class AlertSubscription(models.Model):
    """Represents a user's election to be notified of specific alert classes"""
    user = models.ForeignKey(User, related_name='alert_subscriptions')
    alert_type = models.ForeignKey(ContentType)
    # TODO: alert thresholds?

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']


class AlertEmail(models.Model):
    """Record of which alerts an email has been emitted for"""
    alerts = models.ManyToManyField(AlertState)

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    def __str__(self):
        str = ""
        for a in self.alerts.all():
            str += " %s" % a
        return str
