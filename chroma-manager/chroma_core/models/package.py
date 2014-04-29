#
# INTEL CONFIDENTIAL
#
# Copyright 2013-2014 Intel Corporation All Rights Reserved.
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


from collections import namedtuple
from chroma_core.services import log_register

from django.db import models
from django.db.models import CharField, ForeignKey, IntegerField

log = log_register('package_update')

try:
    import rpm
    rpm  # silence pyflakes
except ImportError:
    # For pure-python environments (i.e. not EL6), a weak implementation just good
    # enough to make it through some tests.
    log.warning("Cannot import rpm module, using dummy version (this is only OK if you are running in development mode)")

    class rpm(object):
        @classmethod
        def labelCompare(cls, a, b):
            return cmp(a, b)


class Package(models.Model):
    class Meta:
        app_label = 'chroma_core'

    name = CharField(max_length=128, unique=True)


class PackageVersion(models.Model):
    class Meta:
        app_label = 'chroma_core'
        unique_together = ('package', 'version', 'release')

    package = ForeignKey('Package')
    epoch = IntegerField()
    version = CharField(max_length=128)
    release = CharField(max_length=128)
    arch = CharField(max_length=32)


class PackageInstallation(models.Model):
    class Meta:
        app_label = 'chroma_core'
        unique_together = ('package_version', 'host')

    package_version = ForeignKey('PackageVersion')
    host = ForeignKey('ManagedHost')


class PackageAvailability(models.Model):
    class Meta:
        app_label = 'chroma_core'
        unique_together = ('package_version', 'host')

    package_version = ForeignKey('PackageVersion')
    host = ForeignKey('ManagedHost')


class VersionInfoList(list):
    """
    Wrap a list of tuples to allow iterating over it as if it's a
    list of VersionInfos
    """
    def __iter__(self):
        for t in super(VersionInfoList, self).__iter__():
            yield VersionInfo(*t)

    def __getitem__(self, item):
        return VersionInfo(super(VersionInfoList, self).__getitem__(item))


class VersionInfo(namedtuple('BaseVersionInfo', ['epoch', 'version', 'release', 'arch'])):
    """
    Wrap tuples of version information to avoid hardcoding tuple manipulation
    """
    def __cmp__(self, other):
        return rpm.labelCompare((self.epoch, self.version, self.release), (other.epoch, other.version, other.release))


def update(host, package_report):
    """
    Update the Package, PackageVersion, PackageInstallation and PackageAvailability models
    according to a report from a storage server.

    :return: True if updates are available, else False
    """
    updates = False

    installed_ids = []
    available_ids = []

    def _updates_available(installed_versions, available_versions):
        # Map of arch to highest installed version
        max_installed_version = {}

        for installed_info in installed_versions:
            max_inst = max_installed_version.get(installed_info.arch, None)
            if max_inst is None or installed_info > max_inst:
                max_installed_version[installed_info.arch] = installed_info

        for available_info in available_versions:
            max_inst = max_installed_version.get(available_info.arch, None)
            if max_inst is not None and available_info > max_inst:
                log.debug("Update available: %s > %s" % (available_info, max_inst))
                return True

        return False

    for repo_name, repo_packages in package_report.items():
        for package_name, package_data in repo_packages.items():
            for version_info in VersionInfoList(package_data['installed']):
                package, created = Package.objects.get_or_create(name=package_name)
                package_version, created = PackageVersion.objects.get_or_create(
                    package=package, epoch=version_info.epoch, version=version_info.version,
                    release=version_info.release, arch=version_info.arch)
                installed_package, created = PackageInstallation.objects.get_or_create(
                    package_version=package_version,
                    host=host)
                installed_ids.append(installed_package.id)

            for version_info in VersionInfoList(package_data['available']):
                package, created = Package.objects.get_or_create(name=package_name)
                package_version, created = PackageVersion.objects.get_or_create(
                    package=package, epoch=version_info.epoch, version=version_info.version,
                    release=version_info.release, arch=version_info.arch)
                available_package, created = PackageAvailability.objects.get_or_create(
                    package_version=package_version,
                    host=host)
                available_ids.append(available_package.id)

            # Are there any installed packages from this bundle with updates available?
            updates = updates or _updates_available(VersionInfoList(
                package_data['installed']), VersionInfoList(package_data['available']))

    # Remove any old package records
    PackageInstallation.objects.exclude(id__in=installed_ids).filter(host=host).delete()
    PackageAvailability.objects.exclude(id__in=available_ids).filter(host=host).delete()
    PackageVersion.objects.filter(packageinstallation=None, packageavailability=None).delete()
    Package.objects.filter(packageversion=None).delete()

    return updates
