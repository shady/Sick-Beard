# coding=UTF-8
import random
import unittest

import test_lib as test

import sys, os.path
sys.path.append(os.path.abspath('..'))
sys.path.append(os.path.abspath('../lib'))


from sickbeard.postProcessor import PostProcessor
import sickbeard
from sickbeard.tv import TVEpisode,TVShow

class PPInitTests(unittest.TestCase):

    def setUp(self):
        self.pp = PostProcessor(test.FILEPATH)
        
    def test_init_file_name(self):
        self.assertEqual(self.pp.file_name, test.FILENAME)
 
    def test_init_folder_name(self):
        self.assertEqual(self.pp.folder_name, test.SHOWNAME)

class PPPrivateTests(test.SickbeardTestDBCase):


    def setUp(self):
        super(PPPrivateTests, self).setUp()
        
        sickbeard.showList = [TVShow(0000),TVShow(0001)]
        
        self.pp = PostProcessor(test.FILEPATH)
        self.show_obj = TVShow(0002)
        
        self.db = test.db.DBConnection()
        newValueDict = {"tvdbid": 1002,
                        "name": test.SHOWNAME,
                        "description": "description",
                        "airdate": 1234,
                        "hasnfo": 1,
                        "hastbn": 1,
                        "status": 404,
                        "location": test.FILEPATH}
        controlValueDict = {"showid": 0002,
                            "season": test.SEASON,
                            "episode": test.EPISODE}

        # use a custom update/insert method to get the data into the DB
        self.db.upsert("tv_episodes", newValueDict, controlValueDict)
        
        self.ep_obj = TVEpisode(self.show_obj, test.SEASON, test.EPISODE, test.FILEPATH)
    
    def test__find_ep_destination_folder(self):
        self.show_obj.location = test.FILEDIR
        self.ep_obj.show.seasonfolders = 1
        sickbeard.SEASON_FOLDERS_FORMAT = 'Season %02d'
        calculatedPath = self.pp._find_ep_destination_folder(self.ep_obj)
        ecpectedPath = os.path.join(test.FILEDIR, "Season 0"+str(test.SEASON))
        self.assertEqual(calculatedPath,ecpectedPath)


class PPBasicTests(test.SickbeardTestDBCase):
    def setUp(self):
        super(PPBasicTests, self).setUp()
        self.pp = PostProcessor(test.FILEPATH)
    
    @unittest.skip("this test is not fully configured / implmented")
    def test_process(self):
        self.assertTrue(self.pp.process())


if __name__ == '__main__':
    print "=================="
    print "STARTING - PostProcessor TESTS"
    print "=================="
    print "######################################################################"
    suite = unittest.TestLoader().loadTestsFromTestCase(PPInitTests)
    unittest.TextTestRunner(verbosity=2).run(suite)
    print "######################################################################"
    suite = unittest.TestLoader().loadTestsFromTestCase(PPPrivateTests)
    unittest.TextTestRunner(verbosity=2).run(suite)
    print "######################################################################"
    suite = unittest.TestLoader().loadTestsFromTestCase(PPBasicTests)
    unittest.TextTestRunner(verbosity=2).run(suite)
