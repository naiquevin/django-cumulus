import datetime
import optparse
import os
from fnmatch import fnmatch

import cloudfiles

from django.conf import settings
from django.core.management.base import BaseCommand
from cumulus.settings import CUMULUS

class Command(BaseCommand):
    help = "Synchronizes selected static media to cloud files."

    option_list = BaseCommand.option_list + (
        optparse.make_option('-w', '--wipe',
            action='store_true', dest='wipe', default=False,
            help="Wipes out entire contents of container first."),
        optparse.make_option('-t', '--test-run',
            action='store_true', dest='test_run', default=False,
            help="Performs a test run of the sync.")
    )

    # settings from cumulus.settings
    USERNAME         = CUMULUS['USERNAME']
    API_KEY          = CUMULUS['API_KEY']
    STATIC_CONTAINER = CUMULUS['STATIC_CONTAINER']
    USE_SERVICENET   = CUMULUS['SERVICENET']
    FILTER_LIST      = CUMULUS['FILTER_LIST']
    AUTH_URL         = CUMULUS['AUTH_URL']

    # paths
    DIRECTORY        = os.path.abspath(settings.STATIC_ROOT)
    STATIC_URL       = settings.STATIC_URL

    if not DIRECTORY.endswith('/'):
        DIRECTORY = DIRECTORY + '/'

    if STATIC_URL.startswith('/'):
        STATIC_URL = STATIC_URL[1:]

    local_object_names = []
    create_count = 0
    upload_count = 0
    update_count = 0
    skip_count = 0
    delete_count = 0
    conn = None
    container = None

    def handle(self, *args, **options):
        self.wipe = options.get('wipe')
        self.test_run = options.get('test_run')
        self.verbosity = int(options.get('verbosity'))
        self.patterns = args
        self.sync_files()

    def sync_files(self):
        self.conn = cloudfiles.get_connection(username = self.USERNAME,
                                              api_key = self.API_KEY,
                                              authurl = self.AUTH_URL,
                                              servicenet=self.USE_SERVICENET)

        # this script assumes that the container already exists and is
        # public
        self.container = self.conn.get_container(self.STATIC_CONTAINER)

        file_paths = self.get_selected_files()
        rel_paths = [os.path.relpath(f, '../') for f in file_paths]

        # if -w option is provided, wipe out the selected files from
        # the container
        if self.wipe:
            if self.test_run:
                print "Wipe would delete %d objects." % (len(file_paths),)
            else:
                c = 0
                for cloud_obj in self.container.get_objects():
                    if cloud_obj.name in rel_paths:
                        c += 1
                        self.container.delete_object(cloud_obj.name)
                print "Deleted %d objects..." % (c,)

        # upload files
        self.upload_files(file_paths)

        # print out the final tally to the cmd line
        self.update_count = self.upload_count - self.create_count
        print
        if self.test_run:
            print "Test run complete with the following results:"
        print "Skipped %d. Created %d. Updated %d. Deleted 0." % (self.skip_count,
                                                                  self.create_count,
                                                                  self.update_count)

    def get_selected_files(self):
        selected = []
        for root, dirs, files in os.walk(self.DIRECTORY):
            for f in files:
                if any([fnmatch(f, p) for p in self.patterns]):
                    selected.append(os.path.join(root, f))
        return selected

    def upload_files(self, file_paths):
        # upload or skip items
        for file_path in file_paths:

            object_name = self.STATIC_URL + file_path.split(self.DIRECTORY)[1]
            self.local_object_names.append(object_name)

            try:
                cloud_obj = self.container.get_object(object_name)
            except cloudfiles.errors.NoSuchObject:
                cloud_obj = self.container.create_object(object_name)
                self.create_count += 1

            cloud_datetime = (cloud_obj.last_modified and
                              datetime.datetime.strptime(
                                cloud_obj.last_modified,
                                "%a, %d %b %Y %H:%M:%S %Z"
                              ) or None)
            local_datetime = datetime.datetime.utcfromtimestamp(
                                               os.stat(file_path).st_mtime)
            if cloud_datetime and local_datetime < cloud_datetime:
                self.skip_count += 1
                if self.verbosity > 1:
                    print "Skipped %s: not modified." % object_name
                continue

            if not self.test_run:
                cloud_obj.load_from_filename(file_path)

            self.upload_count += 1
            if self.verbosity > 1:
                print "Uploaded", cloud_obj.name
