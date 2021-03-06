# Author: Nic Wolfe <nic@wolfeden.ca>
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of Sick Beard.
#
# Sick Beard is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Sick Beard is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Sick Beard.  If not, see <http://www.gnu.org/licenses/>.


import StringIO, zlib, gzip
import os
import stat
import urllib, urllib2
import re, socket
import shutil
import locale

import sickbeard

from sickbeard.exceptions import MultipleShowObjectsException, EpisodeNotFoundByAbsoluteNumerException
from sickbeard import logger, classes
from sickbeard.common import USER_AGENT, mediaExtensions, XML_NSMAP

from sickbeard import db
from sickbeard import encodingKludge as ek
from sickbeard.exceptions import ex

from lib.tvdb_api import tvdb_api, tvdb_exceptions

import xml.etree.cElementTree as etree
from sickbeard.name_parser.parser import NameParser, InvalidNameException
import lib.adba as adba

urllib._urlopener = classes.SickBeardURLopener()

def indentXML(elem, level=0):
    '''
    Does our pretty printing, makes Matt very happy
    '''
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indentXML(elem, level+1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        # Strip out the newlines from text
        if elem.text:
            elem.text = elem.text.replace('\n', ' ')
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

def replaceExtension(file, newExt):
    '''
    >>> replaceExtension('foo.avi', 'mkv')
    'foo.mkv'
    >>> replaceExtension('.vimrc', 'arglebargle')
    '.vimrc'
    >>> replaceExtension('a.b.c', 'd')
    'a.b.d'
    >>> replaceExtension('', 'a')
    ''
    >>> replaceExtension('foo.bar', '')
    'foo.'
    '''
    sepFile = file.rpartition(".")
    if sepFile[0] == "":
        return file
    else:
        return sepFile[0] + "." + newExt

def isMediaFile (file):
    # ignore samples
    if re.search('(^|[\W_])sample\d*[\W_]', file):
        return False

    # ignore MAC OS's retarded "resource fork" files
    if file.startswith('._'):
        return False

    sepFile = file.rpartition(".")
    if sepFile[2].lower() in mediaExtensions:
        return True
    else:
        return False

def sanitizeFileName (name):
    '''
    >>> sanitizeFileName('a/b/c')
    'a-b-c'
    >>> sanitizeFileName('abc')
    'abc'
    >>> sanitizeFileName('a"b')
    'ab'
    '''
    for x in "\\/*":
        name = name.replace(x, "-")
    for x in ":\"<>|?":
        name = name.replace(x, "")
    return name


def getURL (url, headers=[]):
    """
    Returns a byte-string retrieved from the url provider.
    """

    opener = urllib2.build_opener()
    opener.addheaders = [('User-Agent', USER_AGENT), ('Accept-Encoding', 'gzip,deflate')]
    for cur_header in headers:
        opener.addheaders.append(cur_header)
    usock = opener.open(url)
    url = usock.geturl()

    encoding = usock.info().get("Content-Encoding")

    try:
        if encoding in ('gzip', 'x-gzip', 'deflate'):
            content = usock.read()
            if encoding == 'deflate':
                data = StringIO.StringIO(zlib.decompress(content))
            else:
                data = gzip.GzipFile('', 'rb', 9, StringIO.StringIO(content))
            result = data.read()

        else:
            result = usock.read()
            usock.close()
    except socket.timeout:
        logger.log(u"Timed out while loading URL "+url, logger.WARNING)
        return None

    return result

def findCertainShow (showList, tvdbid):
    results = filter(lambda x: x.tvdbid == tvdbid, showList)
    if len(results) == 0:
        return None
    elif len(results) > 1:
        raise MultipleShowObjectsException()
    else:
        return results[0]

def findCertainTVRageShow (showList, tvrid):

    if tvrid == 0:
        return None

    results = filter(lambda x: x.tvrid == tvrid, showList)

    if len(results) == 0:
        return None
    elif len(results) > 1:
        raise MultipleShowObjectsException()
    else:
        return results[0]


def makeDir (dir):
    if not ek.ek(os.path.isdir, dir):
        try:
            ek.ek(os.makedirs, dir)
        except OSError:
            return False
    return True

def makeShowNFO(showID, showDir):

    logger.log(u"Making NFO for show "+str(showID)+" in dir "+showDir, logger.DEBUG)

    if not makeDir(showDir):
        logger.log(u"Unable to create show dir, can't make NFO", logger.ERROR)
        return False

    showObj = findCertainShow(sickbeard.showList, showID)
    if not showObj:
        logger.log(u"This should never have happened, post a bug about this!", logger.ERROR)
        raise Exception("BAD STUFF HAPPENED")

    tvdb_lang = showObj.lang
    # There's gotta be a better way of doing this but we don't wanna
    # change the language value elsewhere
    ltvdb_api_parms = sickbeard.TVDB_API_PARMS.copy()

    if tvdb_lang and not tvdb_lang == 'en':
        ltvdb_api_parms['language'] = tvdb_lang

    t = tvdb_api.Tvdb(actors=True, **ltvdb_api_parms)

    try:
        myShow = t[int(showID)]
    except tvdb_exceptions.tvdb_shownotfound:
        logger.log(u"Unable to find show with id " + str(showID) + " on tvdb, skipping it", logger.ERROR)
        raise

    except tvdb_exceptions.tvdb_error:
        logger.log(u"TVDB is down, can't use its data to add this show", logger.ERROR)
        raise

    # check for title and id
    try:
        if myShow["seriesname"] == None or myShow["seriesname"] == "" or myShow["id"] == None or myShow["id"] == "":
            logger.log(u"Incomplete info for show with id " + str(showID) + " on tvdb, skipping it", logger.ERROR)

            return False
    except tvdb_exceptions.tvdb_attributenotfound:
        logger.log(u"Incomplete info for show with id " + str(showID) + " on tvdb, skipping it", logger.ERROR)

        return False

    tvNode = buildNFOXML(myShow)
    # Make it purdy
    indentXML( tvNode )
    nfo = etree.ElementTree( tvNode )

    logger.log(u"Writing NFO to "+os.path.join(showDir, "tvshow.nfo"), logger.DEBUG)
    nfo_filename = os.path.join(showDir, "tvshow.nfo").encode('utf-8')
    nfo_fh = open(nfo_filename, 'w')
    nfo.write( nfo_fh, encoding="utf-8" )

    return True

def buildNFOXML(myShow):
    '''
    Build an etree.Element of the root node of an NFO file with the
    data from `myShow`, a TVDB show object.

    >>> from collections import defaultdict
    >>> from xml.etree.cElementTree import tostring
    >>> show = defaultdict(lambda: None, _actors=[])
    >>> tostring(buildNFOXML(show))
    '<tvshow xsd="http://www.w3.org/2001/XMLSchema" xsi="http://www.w3.org/2001/XMLSchema-instance"><title /><rating /><plot /><episodeguide><url /></episodeguide><mpaa /><id /><genre /><premiered /><studio /></tvshow>'
    >>> show['seriesname'] = 'Peaches'
    >>> tostring(buildNFOXML(show))
    '<tvshow xsd="http://www.w3.org/2001/XMLSchema" xsi="http://www.w3.org/2001/XMLSchema-instance"><title>Peaches</title><rating /><plot /><episodeguide><url /></episodeguide><mpaa /><id /><genre /><premiered /><studio /></tvshow>'
    >>> show['contentrating'] = 'PG'
    >>> tostring(buildNFOXML(show))
    '<tvshow xsd="http://www.w3.org/2001/XMLSchema" xsi="http://www.w3.org/2001/XMLSchema-instance"><title>Peaches</title><rating /><plot /><episodeguide><url /></episodeguide><mpaa>PG</mpaa><id /><genre /><premiered /><studio /></tvshow>'
    >>> show['genre'] = 'Fruit|Edibles'
    >>> tostring(buildNFOXML(show))
    '<tvshow xsd="http://www.w3.org/2001/XMLSchema" xsi="http://www.w3.org/2001/XMLSchema-instance"><title>Peaches</title><rating /><plot /><episodeguide><url /></episodeguide><mpaa>PG</mpaa><id /><genre>Fruit / Edibles</genre><premiered /><studio /></tvshow>'
    '''
    tvNode = etree.Element( "tvshow" )
    for ns in XML_NSMAP.keys():
        tvNode.set(ns, XML_NSMAP[ns])

    title = etree.SubElement( tvNode, "title" )
    if myShow["seriesname"] != None:
        title.text = myShow["seriesname"]

    rating = etree.SubElement( tvNode, "rating" )
    if myShow["rating"] != None:
        rating.text = myShow["rating"]

    plot = etree.SubElement( tvNode, "plot" )
    if myShow["overview"] != None:
        plot.text = myShow["overview"]

    episodeguide = etree.SubElement( tvNode, "episodeguide" )
    episodeguideurl = etree.SubElement( episodeguide, "url" )
    if myShow["id"] != None:
        showurl = sickbeard.TVDB_BASE_URL + '/series/' + myShow["id"] + '/all/en.zip'
        episodeguideurl.text = showurl

    mpaa = etree.SubElement( tvNode, "mpaa" )
    if myShow["contentrating"] != None:
        mpaa.text = myShow["contentrating"]

    tvdbid = etree.SubElement( tvNode, "id" )
    if myShow["id"] != None:
        tvdbid.text = myShow["id"]

    genre = etree.SubElement( tvNode, "genre" )
    if myShow["genre"] != None:
        genre.text = " / ".join([x for x in myShow["genre"].split('|') if x != ''])

    premiered = etree.SubElement( tvNode, "premiered" )
    if myShow["firstaired"] != None:
        premiered.text = myShow["firstaired"]

    studio = etree.SubElement( tvNode, "studio" )
    if myShow["network"] != None:
        studio.text = myShow["network"]

    for actor in myShow['_actors']:

        cur_actor = etree.SubElement( tvNode, "actor" )

        cur_actor_name = etree.SubElement( cur_actor, "name" )
        cur_actor_name.text = actor['name']
        cur_actor_role = etree.SubElement( cur_actor, "role" )
        cur_actor_role_text = actor['role']

        if cur_actor_role_text != None:
            cur_actor_role.text = cur_actor_role_text

        cur_actor_thumb = etree.SubElement( cur_actor, "thumb" )
        cur_actor_thumb_text = actor['image']

        if cur_actor_thumb_text != None:
            cur_actor_thumb.text = cur_actor_thumb_text

    return tvNode


def searchDBForShow(regShowName):
    """Return False|(tvdb_id,show_name)
    Sanitize given show name into multiple versions and see if we have a record of that show name in the DB
    """
    showNames = [re.sub('[. -]', ' ', regShowName),regShowName]

    myDB = db.DBConnection()

    yearRegex = "([^()]+?)\s*(\()?(\d{4})(?(2)\))$"

    for showName in showNames:

        sqlResults = myDB.select("SELECT * FROM tv_shows WHERE show_name LIKE ? OR tvr_name LIKE ?", [showName, showName])

        # if we find exactly one show return its name and tvdb_id
        if len(sqlResults) == 1:
            return (int(sqlResults[0]["tvdb_id"]), sqlResults[0]["show_name"])
        else:
            tvdbid = get_tvdbid(showName,sickbeard.showList)
       
       
        #TODO: this is bad taking the other function and doing a lookup in the db. REFACTORE! this whole thing
        if tvdbid:
            sqlResults = myDB.select("SELECT * FROM tv_shows WHERE tvdb_id = ?", [tvdbid])
            # if we find exactly one show return its name and tvdb_id
            if len(sqlResults) == 1:
                return (int(sqlResults[0]["tvdb_id"]), sqlResults[0]["show_name"])

        else:
            # if we didn't get exactly one result then try again with the year stripped off if possible
            match = re.match(yearRegex, showName)
            if match and match.group(1):
                logger.log(u"Unable to match original name but trying to manually strip and specify show year", logger.DEBUG)
                sqlResults = myDB.select("SELECT * FROM tv_shows WHERE (show_name LIKE ? OR tvr_name LIKE ?) AND startyear = ?", [match.group(1)+'%', match.group(1)+'%', match.group(3)])

            if len(sqlResults) == 0:
                logger.log(u"Unable to match a record in the DB for "+showName, logger.DEBUG)
                continue
            elif len(sqlResults) > 1:
                logger.log(u"Multiple results for "+showName+" in the DB, unable to match show name", logger.DEBUG)
                continue
            else:
                return (int(sqlResults[0]["tvdb_id"]), sqlResults[0]["show_name"])


    return None

def sizeof_fmt(num):
    '''
    >>> sizeof_fmt(2)
    '2.0 bytes'
    >>> sizeof_fmt(1024)
    '1.0 KB'
    >>> sizeof_fmt(2048)
    '2.0 KB'
    >>> sizeof_fmt(2**20)
    '1.0 MB'
    >>> sizeof_fmt(1234567)
    '1.2 MB'
    '''
    for x in ['bytes','KB','MB','GB','TB']:
        if num < 1024.0:
            return "%3.1f %s" % (num, x)
        num /= 1024.0

def listMediaFiles(dir):

    if not dir or not ek.ek(os.path.isdir, dir):
        return []

    files = []
    for curFile in ek.ek(os.listdir, dir):
        fullCurFile = ek.ek(os.path.join, dir, curFile)

        # if it's a dir do it recursively
        if ek.ek(os.path.isdir, fullCurFile) and not curFile.startswith('.') and not curFile == 'Extras':
            files += listMediaFiles(fullCurFile)

        elif isMediaFile(curFile):
            files.append(fullCurFile)

    return files

def copyFile(srcFile, destFile):
    ek.ek(shutil.copyfile, srcFile, destFile)
    try:
        ek.ek(shutil.copymode, srcFile, destFile)
    except OSError:
        pass

def moveFile(srcFile, destFile):
    try:
        ek.ek(os.rename, srcFile, destFile)
        fixSetGroupID(destFile)
    except OSError:
        copyFile(srcFile, destFile)
        ek.ek(os.unlink, srcFile)

def rename_file(old_path, new_name):

    old_path_list = ek.ek(os.path.split, old_path)
    old_file_ext = os.path.splitext(old_path_list[1])[1]

    new_path = ek.ek(os.path.join, old_path_list[0], sanitizeFileName(new_name) + old_file_ext)

    logger.log(u"Renaming from " + old_path + " to " + new_path)

    try:
        ek.ek(os.rename, old_path, new_path)
    except (OSError, IOError), e:
        logger.log(u"Failed renaming " + old_path + " to " + new_path + ": " + ex(e), logger.ERROR)
        return False

    return new_path

def chmodAsParent(childPath):
    if os.name == 'nt' or os.name == 'ce':
        return

    parentPath = ek.ek(os.path.dirname, childPath)
    
    if not parentPath:
        logger.log(u"No parent path provided in "+childPath+", unable to get permissions from it", logger.DEBUG)
        return
    
    parentMode = stat.S_IMODE(os.stat(parentPath)[stat.ST_MODE])

    if ek.ek(os.path.isfile, childPath):
        childMode = fileBitFilter(parentMode)
    else:
        childMode = parentMode

    try:
        ek.ek(os.chmod, childPath, childMode)
        logger.log(u"Setting permissions for %s to %o as parent directory has %o" % (childPath, childMode, parentMode), logger.DEBUG)
    except OSError:
        logger.log(u"Failed to set permission for %s to %o" % (childPath, childMode), logger.ERROR)

def fileBitFilter(mode):
    for bit in [stat.S_IXUSR, stat.S_IXGRP, stat.S_IXOTH, stat.S_ISUID, stat.S_ISGID]:
        if mode & bit:
            mode -= bit

    return mode

def fixSetGroupID(childPath):
    if os.name == 'nt' or os.name == 'ce':
        return

    parentPath = ek.ek(os.path.dirname, childPath)
    parentStat = os.stat(parentPath)
    parentMode = stat.S_IMODE(parentStat[stat.ST_MODE])

    if parentMode & stat.S_ISGID:
        parentGID = parentStat[stat.ST_GID]
        childGID = os.stat(childPath)[stat.ST_GID]

        if childGID == parentGID:
            return

        try:
            ek.ek(os.chown, childPath, -1, parentGID)  #@UndefinedVariable - only available on UNIX
            logger.log(u"Respecting the set-group-ID bit on the parent directory for %s" % (childPath), logger.DEBUG)
        except OSError:
            logger.log(u"Failed to respect the set-group-ID bit on the parent directory for %s (setting group ID %i)" % (childPath, parentGID), logger.ERROR)

def is_anime_in_show_list():
    for show in sickbeard.showList:
        if show.is_anime:
            return True
    return False

def update_anime_support():
    sickbeard.ANIMESUPPORT = is_anime_in_show_list()

def get_all_episodes_from_absolute_number(show, tvdb_id, absolute_numbers):
    if len(absolute_numbers) == 0:
        raise EpisodeNotFoundByAbsoluteNumerException()

    episodes = []
    season = None
    
    if not show and not tvdb_id:
        return (season, episodes)
    
    if not show and tvdb_id:
        show = findCertainShow(sickbeard.showList, tvdb_id)

    for absolute_number in absolute_numbers:
        ep = show.getEpisode(None, None,absolute_number=absolute_number)
        if ep:
            episodes.append(ep.episode)
        else:
            raise EpisodeNotFoundByAbsoluteNumerException()
        season = ep.season # this will always take the last found seson so eps that cross the season border are not handeled well
    
    return (season, episodes)

def parse_result_wrapper(show, toParse, showList=[], tvdbActiveLookUp=False):
    """Retruns a parse result or a InvalidNameException
        it will try to take the correct regex for the show if given
        if not given it will try Anime first then Normal
        if name is parsed as anime it will lookup the tvdbid and check if we have it as an anime
        only if both is true we will consider it an anime
        
        to get the tvdbid the tvdbapi might be used if tvdbActiveLookUp is True
    """
    if len(showList) == 0:
        showList = sickbeard.showList

    if show and show.is_anime:
        modeList = [NameParser.ANIME_REGEX,NameParser.NORMAL_REGEX]    
    elif show and not show.is_anime:
        modeList = [NameParser.NORMAL_REGEX]
    else: # this will be chosen if no show is given so in cache-,rss-,pp search
        modeList = [NameParser.ANIME_REGEX,NameParser.NORMAL_REGEX]    
        
    for mode in modeList:
        try:
            myParser = NameParser(regexMode=mode)                
            parse_result = myParser.parse(toParse)
        except InvalidNameException:
            pass
        else:
            if mode == NameParser.ANIME_REGEX and not (show and show.is_anime):
                tvdbid = get_tvdbid(parse_result.series_name, showList, tvdbActiveLookUp)
                if not tvdbid or not check_for_anime(tvdbid,showList): # if we didnt get an tvdbid or the show is not an anime (in our db) we will chose the next regex mode
                    continue
                else: # this means it was an anime
                    break
            break
    else:
        raise InvalidNameException("Unable to parse "+toParse)
    return parse_result


def _check_against_names(name, show):
    nameInQuestion = full_sanitizeSceneName(name)

    showNames = [show.name]
    showNames.extend(sickbeard.scene_exceptions.get_scene_exceptions(show.tvdbid))

    for showName in showNames:
        nameFromList = full_sanitizeSceneName(showName)
        # i'll leave this here for historical resons but i changed the find() into a "==" which resolves this problem
        # FIXME: this is ok for most shows but will give false positives on:
        """nameFromList = "show name: special version"
           nameInQuestion = "show name"
           ->will match

           but the otherway around:

           nameFromList = "show name"
           nameInQuestion = "show name: special version"
           ->will not work

           athough the first example will only occur during pp
           and the second example is good that it wont match

        """
        """
        regex = "^."+ ".*"
        match = re.match(regex, curName)
        
        if not match:
            singleName = False
            break
        """
        
        #logger.log(u"Comparing names: '"+nameFromList+"' vs '"+nameInQuestion+"'", logger.DEBUG)
        if nameFromList == nameInQuestion:
            return True

    return False


def get_tvdbid(name, showList, useTvdb=False):
    logger.log(u"Trying to get the tvdbid for "+name, logger.DEBUG)
            
    for show in showList:
        if _check_against_names(name, show):
            logger.log(u"Matched "+name+" in the showlist to the show "+show.name, logger.DEBUG)
            return show.tvdbid

    if useTvdb:
        try:
            t = tvdb_api.Tvdb(custom_ui=classes.ShowListUI, **sickbeard.TVDB_API_PARMS)
            showObj = t[name]
        except (tvdb_exceptions.tvdb_exception):
            # if none found, search on all languages
            try:
                # There's gotta be a better way of doing this but we don't wanna
                # change the language value elsewhere
                ltvdb_api_parms = sickbeard.TVDB_API_PARMS.copy()
    
                ltvdb_api_parms['search_all_languages'] = True
                t = tvdb_api.Tvdb(custom_ui=classes.ShowListUI, **ltvdb_api_parms)
                showObj = t[name]
            except (tvdb_exceptions.tvdb_exception, IOError):
                pass
    
            return 0
        except (IOError):
            return 0
        else:
            return int(showObj["id"])
            
    return 0 
    
 
def check_for_anime(tvdb_id,showList=[],forceDB=False):
    """
    Check if the show is a anime
    """
    if not forceDB and len(showList):
        for show in showList:
            if show.tvdbid == tvdb_id and show.is_anime:
                return True
    
    
    elif tvdb_id:
        myDB = db.DBConnection()
        isAbsoluteNumberSQlResult = myDB.select("SELECT anime,show_name FROM tv_shows WHERE tvdb_id = ?", [tvdb_id])
        if isAbsoluteNumberSQlResult and int(isAbsoluteNumberSQlResult[0][0]) > 0:
            logger.log(u"This show (tvdbid:"+str(tvdb_id)+") is flaged as an anime", logger.DEBUG)
            return True
    return False 

def set_up_anidb_connection():
        if not sickbeard.USE_ANIDB:
            logger.log(u"Usage of anidb disabled. Skiping", logger.DEBUG)
            return False
        
        if not sickbeard.ANIDB_USERNAME and not sickbeard.ANIDB_PASSWORD:
            logger.log(u"anidb username and/or password are not set. Aborting anidb lookup.", logger.DEBUG)
            return False
        
        if not sickbeard.ADBA_CONNECTION:
            anidb_logger = lambda x : logger.log("ANIDB: "+str(x), logger.DEBUG)
            sickbeard.ADBA_CONNECTION = adba.Connection(keepAlive=True,log=anidb_logger)
        
        if not sickbeard.ADBA_CONNECTION.authed():
            try:
                sickbeard.ADBA_CONNECTION.auth(sickbeard.ANIDB_USERNAME, sickbeard.ANIDB_PASSWORD)
            except Exception,e :
                logger.log(u"exception msg: "+str(e))
                return False
        else:
            return True
 
        return sickbeard.ADBA_CONNECTION.authed()

def set_locale_to_us():
    if locale.getdefaultlocale() != ('en_US', 'ISO8859-1'): 
        try:
            locale.setlocale(locale.LC_TIME, 'en_US')
        except Exception, e:
            logger.log("can't set local to en_US this might lead to errors during time parsing: " + str(e), logger.ERROR)
    
def set_local_to_default():
    if locale.getdefaultlocale() != locale.getlocale(locale.LC_ALL): 
        try:
            locale.setlocale(locale.LC_ALL,'')
        except Exception, e:
            logger.log("can't set local (back) to the default. this might lead to further errors!!: " + str(e), logger.ERROR)


   
def full_sanitizeSceneName(name):
    return re.sub('[. -]', ' ', sanitizeSceneName(name)).lower().lstrip()


def sanitizeSceneName (name, ezrss=False):
    """
    Takes a show name and returns the "scenified" version of it.
    
    ezrss: If true the scenified version will follow EZRSS's cracksmoker rules as best as possible
    
    Returns: A string containing the scene version of the show name given.
    """

    if not ezrss:
        bad_chars = ",:()'!?"
    # ezrss leaves : and ! in their show names as far as I can tell
    else:
        bad_chars = ",()'?"

    # strip out any bad chars
    for x in bad_chars:
        name = name.replace(x, "")

    # tidy up stuff that doesn't belong in scene names
    name = name.replace("- ", ".").replace(" ", ".").replace("&", "and").replace('/','.')
    name = re.sub("\.\.*", ".", name)

    if name.endswith('.'):
        name = name[:-1]

    return name


if __name__ == '__main__':
    import doctest
    doctest.testmod()
