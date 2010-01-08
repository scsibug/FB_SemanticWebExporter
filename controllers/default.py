from applications.sw_exporter.modules.facebook import *
from applications.sw_exporter.modules.settings import swe_settings, fb_settings

import datetime
import time
import rdflib
from rdflib import Graph
from rdflib import plugin
from rdflib.store import Store, NO_STORE, VALID_STORE
from rdflib import Namespace
from rdflib import Literal
from rdflib import BNode
from rdflib import URIRef
from rdflib.constants import TYPE, VALUE
from rdflib.TripleStore import TripleStore
from os import urandom
foafp = "http://xmlns.com/foaf/0.1/"
rdfs = "http://www.w3.org/2000/01/rdf-schema#"

allowed_formats = ['rdf', 'n3', 'nt', 'turtle', 'pretty-xml']
default_format = 'rdf'

# prefix for saving facebook sessions: append uid, lookup, and get facebook session.
fb_cache_prefix="facebook-"
# prefix  for saving auth tokens: append uid, lookup, and get secret key
token_cache_prefix="swe_token-"

# TODO:
# Don't display triples directly, after ~3000, facebook times out in displaying the page
# Generic functions to add triples from either friends or myself.
# request users email and foaf:Person URI
# Allow users to show only their info, not their friends.
# Publish aggregate data about # of triples served, unique users, etc.
# Direct links are broken when running web2py multiprocess.
#      Need to store tokens in DB, not cache.
# Personal profile document tags, creation date, etc.

def index():
    require_facebook_login(request,fb_settings)
    start_time = time.time()
    facebook=request.facebook
    reqformat = detect_requested_format()
    fbgraph = FacebookGraph(facebook)
    fbgraph.generateThisUsersTriples()
    fbgraph.generateFriendTriples(limit=2)
    graph = fbgraph.graph
    graphserial = graph.serialize(format=reqformat)
    tc = len(graph)
    # put a token into the facebook object, to use for authorization
    # for out-of-band (non-facebook) requests, we can authenticate
    # people by making sure they provide this token in their request.
    # Setting time_expire to zero forces an overwrite of what was in
    # the cache.  This is important because the download link may
    # overwrite/clear/corrupt the cache entry every time, so we need
    # to make sure it has the correct values.
    facebook.swe_token = cache.ram(token_cache_prefix+facebook.uid, lambda:urandom(24).encode('hex'),time_expire=0)
    cached_fb = cache.ram(fb_cache_prefix+facebook.uid, lambda:facebook,time_expire=0)
    tripleslink = generate_triples_link(facebook.uid, reqformat, facebook.swe_token)
    stop_time = time.time()
    db.served_log.insert(fb_user_id=facebook.uid,
                         triple_count=tc,
                         format=reqformat,
                         processing_ms=(stop_time-start_time)*1000.0,
                         timestamp=datetime.datetime.now())
    return dict(message="Hello "+get_facebook_user(request),
                graph=graphserial,
                format=reqformat,
                uid=facebook.uid,
                swe_token=facebook.swe_token,
                triplesbase=swe_settings.SERVER_APP_URL+'default/triples',
                tripleslink=tripleslink,
                baseurl=swe_settings.CANVAS_BASE_URL)

def detect_requested_format():
    reqformat=request.vars.format
    if reqformat not in allowed_formats:
        reqformat = default_format
    return reqformat

# Generate an absolute link to raw triples, for direct downloads.
def generate_triples_link(uid, format, token):
    if not format:
        format = 'rdf'
    if token and uid:
        return swe_settings.SERVER_APP_URL + 'default/triples?' + 'swe_token=' + token + '&uid=' + uid + '&format=' + format
    else:
        return ""

# use cache lookup and provided authz token, to retrieve a facebook object.
# use params to determine what type of graph to build, and what format to provide it in.
# send graph data to user.
def triples():
    start_time = time.time()
    provided_token = request.vars.swe_token # secret token from user
    fb_uid = request.vars.uid # users facebook UID
    foaf_person = request.vars.foaf_person # foaf person URI
    include_friends = request.vars.include_friends # 'true' or 'false'
    facebook = cache.ram(fb_cache_prefix+fb_uid, lambda:None)
    # Don't allow the link to be reused.
    cache.ram.clear(regex=fb_cache_prefix+fb_uid)
    if (not facebook):
        # Should redirect back to facebook app?
        return "This link has expired, please try generating a new link from Facebook."
    correct_token = facebook.swe_token
    if not provided_token:
        return "Provided token is null"
    elif not correct_token:
        return "Could not get the correct token from the facebook session."
    elif (correct_token != provided_token):
        return "Not authorized, or this link has expired."
    reqformat = detect_requested_format()
    fbgraph = FacebookGraph(facebook)
    if foaf_person:
        fbgraph.generateThisUsersTriples(user_uri=URIRef(foaf_person))
    else:
        fbgraph.generateThisUsersTriples()
    if include_friends and include_friends == 'true':
        fbgraph.generateFriendTriples()
    graph = fbgraph.graph
    tc = len(graph)
    graphserial = graph.serialize(format=reqformat)
    if reqformat not in allowed_formats:
        reqformat = default_format
    if reqformat == 'rdf' or reqformat == 'pretty-xml':
        response.headers["Content-Type"] = "application/rdf+xml; charset=utf-8"
        response.headers["Content-disposition"] = "attachment; filename=foaf.rdf"
    elif reqformat == 'n3':
        response.headers["Content-Type"] = "text/n3"
        response.headers["Content-disposition"] = "attachment; filename=foaf.n3"
    elif reqformat == 'nt': # N-Triples are ASCII
        response.headers["Content-Type"] = "text/plain"
        response.headers["Content-disposition"] = "attachment; filename=foaf.nt"
    elif reqformat == 'turtle': # Turtle is UTF-8 always
        response.headers["Content-Type"] = "application/x-turtle"
        response.headers["Content-disposition"] = "attachment; filename=foaf.ttl"
    stop_time = time.time()
    db.served_log.insert(fb_user_id=fb_uid, triple_count=tc, format=reqformat, processing_ms=(stop_time-start_time)*1000.0, timestamp=datetime.datetime.now())
    return graphserial


# Take an RDF graph, foaf-user URI, and the facebook "website" field,
# and try to extract some meaningful URIs.  People often put multiple
# space/newline delimited websites in this field, and leave off the
# scheme (http://).
def sanitize_websites(graph, user, website_field):
    # get a list of whitespace-delimited items in the website field
    websites = website_field.split()
    # Assume all websites start with "http://"
    for website in websites:
        # Strip off trailing characters more likely to be used in a list of
        # entries than to end a valid URL
        website = website.rstrip(',;')
        if website.startswith("http://") or website.startswith("https://"):
            graph.add((user,URIRef(foafp+"homepage"),URIRef(website)))
        elif website.startswith("www"):
            graph.add((user,URIRef(foafp+"homepage"),URIRef("http://"+website)))
        elif (".com" in website) or (".net" in website) or (".org" in website):
            graph.add((user,URIRef(foafp+"homepage"),URIRef("http://"+website)))
        # Text is too sketchy to try and url-ize.

# Take a facebook "website" string, and extract a list of URIs (string
# type) that can be assigned as foaf:homepages.
def extract_homepages(website_field):
    homepages = []
    if not website_field:
        return homepages
    # get a list of whitespace-delimited items in the website field
    websites = website_field.split()
    for website in websites:
        # Strip off trailing characters more likely to be used in a list of
        # entries than to end a valid URL
        website = website.rstrip(',;')
        if website.startswith("http://") or website.startswith("https://"):
            homepages.append(website)
        elif website.startswith("www") or (".com" in website) or (".net" in website) or (".org" in website):
            homepages.append("http://"+website)
        # Else, website is too sketchy to try and url-ize.
    return homepages

class FacebookGraph:
    """RDF graph for facebook data."""
    def __init__(self, facebook):
        self.facebook = facebook
        self.graph = Graph()
        # Setup prefixes
        self.graph.bind("foaf", foafp)

    def generateThisUsersTriples(self,user_uri=None):
        """Generate triples for the facebook user."""
        if user_uri:
            self.me = user_uri
        else:
            self.me = URIRef("#me")
        sr = self._userSearchResults(self.facebook.uid)
        self._generateUsersTriples(self.me,sr)

    def generateAccountProfile(self,personRef,name,profile_url):
        """Add fb account info for the foaf:person using their name and profile url."""
        account = BNode()
        self.attemptAddAsLiteral(account, URIRef(rdfs+"label"), "Facebook account for "+name)
        self.graph.add((personRef, URIRef(foafp+"account"), account))
        self.attemptAddAsURI(account, TYPE, foafp+"OnlineAccount")
        self.attemptAddAsLiteral(account, URIRef(foafp+"accountName"), name)
        self.attemptAddAsURI(account, URIRef(foafp+"accountProfilePage"), profile_url)
        self.attemptAddAsURI(account, URIRef(foafp+"accountServiceHomepage"), "http://www.facebook.com/")

    def _generateUsersTriples(self,personURI,sr):
        self.graph.add((personURI, TYPE, URIRef(foafp+"Person")))
        self.attemptAddAsLiteral(personURI,
                                 URIRef(foafp+"givenName"),
                                 sr[u'first_name'])
        self.attemptAddAsLiteral(personURI,
                                 URIRef(foafp+"familyName"),
                                 sr[u'last_name'])
        if sr[u'first_name'] and sr[u'last_name']:
            name = sr[u'first_name']+" "+sr[u'last_name']
            self.attemptAddAsLiteral(personURI,URIRef(rdfs+"label"),name)
            self.attemptAddAsLiteral(personURI,
                                     URIRef(foafp+"name"),
                                     sr[u'first_name']+" "+sr[u'last_name'])
        self.attemptAddAsLiteral(personURI,URIRef(foafp+"gender"),sr[u'sex'])
        self.attemptAddAsURI(personURI, URIRef(foafp+"img"), sr[u'pic'])
        sites = extract_homepages(sr[u'website'])
        for site in sites:
            self.attemptAddAsURI(personURI, URIRef(foafp+"homepage"), site)
        self.generateAccountProfile(personURI, name, sr[u'profile_url'])

    def generateFriendTriples(self,limit=None):
        """Add all friend entries.  Optional limit on friends added."""
        if limit:
            limit_stmt = " LIMIT "+str(limit)
        else:
            limit_stmt = ""
        # query for all friends
        friendquery = "SELECT uid, first_name, last_name, pic, sex, current_location, profile_url, website FROM user WHERE uid IN (SELECT uid2 FROM friend WHERE uid1 = %s) %s" % (self.facebook.uid, limit_stmt)
        friendresults = self.facebook.fql.query(friendquery)
        for fresult in friendresults:
            thisfriend = BNode()
            self._generateUsersTriples(thisfriend,fresult)
            self.addFriend(thisfriend)

    def addFriend(self,personRef):
        self.attemptAddAsURI(self.me, URIRef(foafp+"knows"), personRef)

    def attemptAddAsLiteral(self, subj, pred, string):
        """Add a triple, if the literal string is defined."""
        if string:
            self.graph.add((subj,pred,Literal(string)))

    def attemptAddAsURI(self, subj, pred, uri):
        """Add a triple, if the URI is defined."""
        if uri:
            self.graph.add((subj,pred,URIRef(uri)))

    def _userSearchResults(self, uid):
        """Return search results for a given user"""
        query = "SELECT uid, first_name, last_name, pic, sex, current_location, profile_url, website FROM user WHERE uid=%s" % uid
        return self.facebook.fql.query(query)[0]
