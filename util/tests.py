#############################################################################
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
#############################################################################
#
#  Project Name        :    IEEE 802.11 Timeline Tool#                                                                            *
#
#  Author              :    Alex Ashley
#
#############################################################################

from util.io import from_isodatetime, flatten, parse_date
from util.tasks import run_test_task_queue
from util.models import SiteURLs
from util.db import bulk_delete
from util.views import import_page, import_progress
from ballot.models import Ballot, DenormalizedBallot, BallotBacklog
from project.models import Project, DenormalizedProject, ProjectBacklog
from timeline.models import DenormalizedProjectBallots, ProjectBallotsBacklog
from report.models import MeetingReport

from django.test import TestCase
from django.test.client import RequestFactory
from django.core.urlresolvers import reverse
from django.contrib.auth import authenticate
from django.db.models.fields import URLField
from django.conf import settings
from django.utils import http

import datetime, decimal
import unittest

class LoginBasedTest(TestCase):    
    def setUp(self):
        self.logged_in = None
        self._user = None
        self._factory = None
        
    def _check_page(self,url, status_code=200):
        response = self.client.get(url)
        if not self.logged_in:
            # not logged in, should redirect to login page
            self.failUnlessEqual(response.status_code, 302)
            self.assertRedirects(response,settings.LOGIN_URL+'?next='+http.urlquote(url))
            self.logged_in = self.client.login(username='test', password='password')
            self.failUnless(self.logged_in, 'Could not log in')
        response = self.client.get(url)
        self.failUnlessEqual(response.status_code, status_code)
        return response
    
    @property
    def user(self):
        if self._user is None:
            self._user = authenticate(username='test', password='password')
        return self._user
    
    @property
    def factory(self):
        if self._factory is None:
            self._factory = RequestFactory()
        return self._factory
    
    def get_request(self,url):
        request = self.factory.get(url)
        request.user = self.user 
        return request
        
class UtilTest(unittest.TestCase):
    def test_from_isodatetime(self):
        """
        Tests converting from ISO 8601 string to Python datetime / timedelta objects
        """
        tests = [
                 ('2009-02-27T10:00:00Z', datetime.datetime(2009,2,27,10,0,0) ),
                 ('PT14H00M00S', datetime.timedelta(hours=14) ),
                 ('PT00H45M00S', datetime.timedelta(minutes=45) ),
                 ('PT01:45:19', datetime.timedelta(hours=1,minutes=45,seconds=19) ),
                 ]
        for test in tests:
            tc = from_isodatetime(test[0])
            self.failUnlessEqual(tc,test[1])

    def test_flatten(self):
        """
        Tests converting Python objects to form suitable for storage
        """
        tests = [
                 ([1,2,3],[1,2,3]),
                 ([1,2L,3],[1,'2',3]),
                 ( [1, 2L, 3, datetime.datetime(2009, 8, 13, 10, 52, 8, 734209)], [1, '2', 3, '2009-08-13T10:52:08.734209Z']),
                 ( (1, 2L, 3, datetime.datetime(2009, 8, 13, 10, 52, 8, 734209)), (1, '2', 3, '2009-08-13T10:52:08.734209Z') ),
                 ( [decimal.Decimal('5.2'), u'Hello World', datetime.date(2009, 8, 13)], ['5.2', 'Hello World', '2009-08-13'] ),
                 ({'a': decimal.Decimal('5.2'), 'c': datetime.date(2009, 8, 13), 'b': u'Hello World'}, {'a': '5.2', 'c': '2009-08-13', 'b': 'Hello World'}),
                 ]
        for test in tests:
            f = flatten(test[0])
            self.failUnlessEqual(f,test[1])
            
    def test_date_parse(self):
        dates = [
                 ('2008-05-03', datetime.datetime(2008,5,3)), 
                 ('05/30/06', datetime.datetime(2006,5,30)), 
                 ('05/30/2006', datetime.datetime(2006,5,30)), 
                 ('Mon Sep 27, 2010', datetime.datetime(2010,9,27)),
                 ('Sep 16 2007 - 23:59 ET', datetime.datetime(2007,9,17,4,59)),
                 ('October 16 2007 - 23:59 ET', datetime.datetime(2007,10,17,4,59)),
                 ('May 2, 2007 - 23:59 ET', datetime.datetime(2007,5,3,4,59)),
                 ('Sep-14', datetime.datetime(2014,9,1)),
                 ('09/xx/14', datetime.datetime(2014,9,1)), 
                 ('May 14', datetime.datetime(2014,5,1)), 
                 ('Oct 2014', datetime.datetime(2014,10,1)), 
                 ('October 7 2014', datetime.datetime(2014,10,7)) ,
                 ('Jul 26 2013', datetime.datetime(2013,7,26)), 
                 ('March 26 2013', datetime.datetime(2013,3,26)) 
                 ]
        for s,d in dates:
            v = parse_date(s)
            self.failIfEqual(v,None,s)
            self.failUnlessEqual(v,d,s)
                   
            
class ImportPageTest(LoginBasedTest):
    NOT_IDEMPOTENT = []

    #def setUp(self):
    #    super(ImportPageTest,self).setUp()
    #    self.user = authenticate(username='test', password='password')
    #    self.factory = RequestFactory()

    def _post_import(self,url,filename,length=0, wipe_projects=False, wipe_ballots=False):
        testfile = open(filename,'r')
        data = {
                'wipe_projects' : wipe_projects,
                'wipe_ballots': wipe_ballots,
                'import' : 'Import',
                'file' : testfile
                }
        try:
            response = self.client.post(url, data, follow=True)
            #request = self.factory.post(url, data)
            #request.user = self.user 
            #response = import_page(request, next='/')
        except:
            raise
        finally:
            testfile.close()
        #progress_url =  response.get('Location')
        self.failUnlessEqual(response.redirect_chain[0][1],302)
        progress = response.context['progress']
        progress_url = reverse('util.views.import_progress',args=[progress.pk])
        self.failUnless(response.redirect_chain[0][0].endswith(progress_url))
        #self.failIf(response.context['errors'])
        if length:
            self.assertContains(response, 'input file contains %d line'%length)
        while progress.finished is None:
            run_test_task_queue(self.client)
            response = self.client.get(progress_url)
            #request = self.factory.get(progress_url)
            #request.user = self.user 
            #response = import_progress(request, progress.pk)
            self.failUnlessEqual(response.status_code, 200)
            progress = response.context['progress']
        done_url = reverse('util.views.import_done',args=[progress.pk])
        response = self.client.get(done_url)
        self.failUnlessEqual(response.status_code, 200)
        return response
        
class ImportHtmlBallotTest(ImportPageTest):
    fixtures = ['site.json','projects.json']
    LB_BALLOT_HTML = 'util/fixtures/LetterBallots.htm'
    SB_BALLOT_HTML = 'util/fixtures/SponsorBallots.htm'
    
    def test_ballot_import(self):
        """
        Tests import page
        """
        url = reverse('util.views.import_page',args=[])
        response = self._check_page(url)
        self.assertContains(response, '<input type="submit" name="submit"')
        
        response = self._post_import(url, self.LB_BALLOT_HTML)
        print response
        counts = {}
        tmodels = { Ballot:0, Project: 0 }
        for m in tmodels.keys():
            self.failIfEqual(m.objects.count(),tmodels[m],msg='%s model has %d items, should have more than %d items'%
                                 (m._meta.verbose_name,m.objects.count(),tmodels[m]))
            counts[m] = m.objects.count()
        tmodels[Ballot] = counts[Ballot]
        
        # Check that a second attempt to import the data does not cause errors and does not add any new objects to the database
        response = self._post_import(url, self.LB_BALLOT_HTML)
        for m in tmodels.keys():
            self.failUnlessEqual(m.objects.count(),counts[m],msg='%s model had %d items, but after a second import has %d'%
                                 (m._meta.verbose_name,counts[m],m.objects.count()))
        
        response = self._post_import(url, self.SB_BALLOT_HTML)
        for m in tmodels.keys():
            self.failIfEqual(m.objects.count(),tmodels[m],msg='%s model has %d items, should have more than %d items'%
                                 (m._meta.verbose_name,m.objects.count(),tmodels[m]))
            counts[m] = m.objects.count()
            
        # Check that a second attempt to import the data does not cause errors 
        # and does not add any new objects to the database
        response = self._post_import(url, self.SB_BALLOT_HTML)
        for m in tmodels.keys():
            self.failUnlessEqual(m.objects.count(),counts[m],msg='%s model had %d items, but after a second import has %d'%
                                 (m._meta.verbose_name,counts[m],m.objects.count()))
            
class ImportHtmlTimelineTest(ImportPageTest):
    fixtures = ['site.json']
    LB_BALLOT_HTML = 'util/fixtures/LetterBallots.htm'
    SB_BALLOT_HTML = 'util/fixtures/SponsorBallots.htm'
    TIMELINE_HTML = 'util/fixtures/Timelines.htm'
    
    def test_timeline_import(self):
        """
        Tests import page with a timelines.html
        """
        url = reverse('util.views.import_page',args=[])
        self._check_page(url)
        response = self._post_import(url, self.TIMELINE_HTML)
        #print 'response',response
        self.assertEqual(Project.objects.count(),37)

class ImportHtmlReportTest(ImportPageTest):
    fixtures = ['site.json']
    
    def test_meeting_import(self):
        url = reverse('util.views.import_page',args=[])
        self._check_page(url)
        response = self._post_import(url, 'util/fixtures/MeetingReports.htm')
        self.assertEqual(MeetingReport.objects.count(),135+7-1)

class ImportCsvPageTest(ImportPageTest):
    fixtures = ['site.json']
    TESTFILE = ('util/fixtures/timeline-2010-11-02-1439.csv' ,187)
    MODELS = [Ballot, Project]
    
    def test_csv_import(self):
        """
        Tests import page with CSV files
        """
            
        url = reverse('util.views.import_page',args=[])
        response = self.client.get(url)
        # not logged in, should redirect to login page
        self.failUnlessEqual(response.status_code, 302)

        login = self.client.login(username='test', password='password')
        self.failUnless(login, 'Could not log in')

        response = self.client.get(url)
        self.failUnlessEqual(response.status_code, 200)
        self.assertContains(response, '<input type="submit" name="submit"')
        #print response
        response = self._post_import(url, self.TESTFILE[0], self.TESTFILE[1])
        counts = {}
        tmodels = {}
        for m in self.MODELS:
            tmodels[m]=0
        for m in tmodels.keys():
            self.failIfEqual(m.objects.count(),tmodels[m],msg='%s model has %d items, should have more than %d items'%
                                 (m._meta.verbose_name,m.objects.count(),tmodels[m]))
            counts[m] = m.objects.count()
        # Check that a second attempt to import the data does not cause errors and does not add any new objects to the database
        response = self._post_import(url, self.TESTFILE[0], self.TESTFILE[1])
        for m in tmodels.keys():
            if m in self.NOT_IDEMPOTENT:
                self.failIfEqual(m.objects.count(),counts[m],msg='%s model had %d items, but after a second import it still has %d'%
                                     (m._meta.verbose_name,counts[m],m.objects.count()))
            else:
                self.failUnlessEqual(m.objects.count(),counts[m],msg='%s model had %d items, but after a second import has %d'%
                                     (m._meta.verbose_name,counts[m],m.objects.count()))
        
class ImportCsvPageTest2(ImportCsvPageTest):
    fixtures = ['site.json','projects.json'] 
    TESTFILE = ('util/fixtures/ballots-2010-11-02-1439.csv',153)
     
class ImportCsvPageTest3(ImportCsvPageTest):
    fixtures = ['site.json','projects.json'] 
    TESTFILE = ('util/fixtures/ballots-zero-fields.csv',3) 
    NOT_IDEMPOTENT = [Ballot]
    
class ImportCsvPageTest4(ImportCsvPageTest):
    fixtures = ['site.json']
    TESTFILE = ('util/fixtures/timeline-2011-03-20-1740.csv', 384)
    MODELS = [Project, Ballot, MeetingReport]
    
    def test_cancel_import(self):
        login = self.client.login(username='test', password='password')
        self.failUnless(login, 'Could not log in')
        testfile = open(self.TESTFILE[0],'r')
        data = {
                'wipe_projects' : False,
                'wipe_ballots': False,
                'cancel' : 'Cancel',
                'file' : testfile
                }
        url = reverse('util.views.import_page',args=[])
        try:
            response = self.client.post(url, data, follow=True)
        except:
            raise
        finally:
            testfile.close()
        try:
            progress = response.context['progress']
            raise AssertionError('Cancelling import failed')
        except KeyError:
            pass
        self.failUnlessEqual(response.redirect_chain[0][1],302)
        
class ImportCsvWipeTest(ImportPageTest):
    fixtures = ['site.json','projects.json','ballots.json','timelines.json','reports.json']
    TESTFILE = ('util/fixtures/timeline-2013-05-23-1708.csv', 452)
    MODELS = [Project, Ballot, MeetingReport]
    
    def test_wipe_import(self):
        self.assertEqual(Project.objects.count(),37)
        self.assertEqual(Ballot.objects.count(),269)
        self.assertEqual(MeetingReport.objects.count(),141)
        login = self.client.login(username='test', password='password')
        self.failUnless(login, 'Could not log in')
        url = reverse('util.views.import_page',args=[])
        response = self._post_import(url, self.TESTFILE[0], self.TESTFILE[1], wipe_projects=True, wipe_ballots=True)
        self.assertEqual(len(response.context['projects']),Project.objects.count())
        self.assertEqual(len(response.context['ballots']),Ballot.objects.count())
        self.assertEqual(len(response.context['reports']),MeetingReport.objects.count())
        self.assertEqual(len(response.context['errors']),0)
        self.assertEqual(Project.objects.count(),37)
        self.assertEqual(Ballot.objects.count(),269)
        self.assertEqual(MeetingReport.objects.count(),141)
        
class MainPageTest(TestCase):
    fixtures = ['site.json']
    
    def test_get_index_view(self):
        "GET tests on front page"
        # The data is ignored, but let's check it doesn't crash the system
        # anyway.
        data = {'var': u'\xf2'}
        response = self.client.get('/', data)

        # Check some response details
        self.failUnlessEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')

class UtilPagesTest(LoginBasedTest):
    fixtures = ['site.json','projects.json','ballots.json']
    
    def test_util_index(self):
        url = reverse('util.views.main_page')
        self._check_page(url)
        
    def test_update_page(self):
        url = reverse('util.views.update_page')
        bulk_delete(DenormalizedProjectBallots)
        bulk_delete(DenormalizedBallot)
        bulk_delete(DenormalizedProject)
        response = self._check_page(url)
        while BallotBacklog.objects.exists() or ProjectBacklog.objects.exists() or ProjectBallotsBacklog.objects.exists():
            run_test_task_queue(self.client)
        self.failUnlessEqual(Project.objects.count(),DenormalizedProject.objects.count())
        self.failUnlessEqual(Ballot.objects.count(),DenormalizedBallot.objects.count())
        self.failUnlessEqual(Project.objects.count(),DenormalizedProjectBallots.objects.count())

class ExportDatabaseTest(TestCase):
    fixtures = ['site.json','projects.json', 'ballots.json', 'timelines.json', 'reports.json']
    
    def test_export(self):
        self.assertGreater(Project.objects.count(), 0)
        self.assertGreater(Ballot.objects.count(), 0)
        self.assertGreater(MeetingReport.objects.count(), 0)
        url = reverse('util.views.export_db',args=[])
        response = self.client.get(url)
        # not logged in, should redirect to login page
        self.failUnlessEqual(response.status_code, 302)

        login = self.client.login(username='test', password='password')
        self.failUnless(login, 'Could not log in')
        response = self.client.get(url)
        for proj in Project.objects.all().iterator():
            for field in proj._meta.fields:
                if field.attname!='slug':
                    value = getattr(proj,field.attname)
                    if value:
                        self.assertContains(response, value, msg_prefix='Project.%s'%field.attname)
        for ballot in Ballot.objects.all().iterator():
            for field in ballot._meta.fields:
                value = getattr(ballot,field.attname)
                if value:
                    self.assertContains(response, value, msg_prefix='Ballot.%s'%field.attname)
        for report in MeetingReport.objects.all().iterator():
            for field in report._meta.fields:
                value = getattr(report,field.attname)
                if value:
                    self.assertContains(response, value, msg_prefix='MeetingReport.%s'%field.attname)
        
            
class EditUrlsPageTest(TestCase):
    fixtures = ['site.json','projects.json']
    
    def test_edit_urls(self):
        """
        Tests edit urls page
        """

        default = SiteURLs.get_urls()
        url = reverse('util.views.edit_urls',args=[])
        response = self.client.get(url)
        # not logged in, should redirect to login page
        self.failUnlessEqual(response.status_code, 302)

        login = self.client.login(username='test', password='password')
        self.failUnless(login, 'Could not log in')
        response = self.client.get(url)
        self.failUnlessEqual(response.status_code, 200)
        self.assertContains(response, '<input type="submit" name="submit"')
        urls = response.context['object']
        post = {'submit':'submit'}
        for field in urls._meta.fields:
            if field.editable and not field.primary_key :
                dft = getattr(default,field.attname)
                a = getattr(urls,field.attname)
                self.failUnlessEqual(a,dft)
                if isinstance(field,URLField):
                    post[field.attname] = a+'/Test'
                else:
                    # assume it's an email field
                    post[field.attname] = 'Test User <test@example-net.org>'
        response = self.client.post(url, post, follow=True)      
        # The POST should have caused the site URLs to change, so get the new URLS and compare them to the defaults
        new_urls = SiteURLs.get_urls()
        for field in urls._meta.fields:
            if not field.primary_key:
                dft = getattr(default,field.attname)
                a = getattr(new_urls,field.attname)
                self.failIfEqual(a,dft)
                if field.editable:
                    self.failUnlessEqual(a,post[field.attname])
        del post['submit']
        post['cancel']='Cancel'
        post['timeline_history'] = 'http://example.domain.com/cancel/test'
        self.client.post(url, post, follow=True)
        self.failIfEqual(post['timeline_history'], new_urls.timeline_history)