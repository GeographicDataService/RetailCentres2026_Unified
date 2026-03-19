"""
Name Assembly & Export for UK Retail Centres.

Replicates the logic of 5_Generate_Exports.R:
  2a. Classification hierarchy (already in gpkg — used directly)
  2b. Name assembly from 4 lookup tables
  2c. Sub-area naming
  2d. Cleanup & deduplication
  2e. Export to gpkg + CSV

Reads lookup CSVs from exports/ and the input gpkg.
"""

import os
import re
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd

warnings.filterwarnings("ignore", category=FutureWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")
GPKG_PATH = os.path.join(BASE_DIR, "rc2025_foursquare_ignoreCounty.gpkg")
CRS_BNG = "EPSG:27700"

# ─── Sub-area manual names ────────────────────────────────────────────
# Curated local names for sub-areas in major city centres.
# Three versions available:
#   "v1" — street-focused, single names where dominant
#   "v2" — neighbourhood/landmark-focused, more two-part names
#   "v3" — web-verified geography + POI data, proper quarter/area names
# Set to None to disable and use pipeline names.
MANUAL_SUBAREA_VERSION = "v4"

MANUAL_SUBAREA_NAMES_V1 = {
    # Liverpool
    "97":   "Liverpool ONE",
    "90":   "Bold Street",
    "288":  "Castle Street",
    "193":  "Church Street & Lime Street",
    "548":  "Hope Street",
    # Manchester
    "17":   "Northern Quarter",
    "34":   "Deansgate & King Street",
    "92":   "Arndale",
    "175":  "Chinatown & Gay Village",
    "332":  "Spinningfields",
    "436":  "Oxford Street",
    "750":  "Piccadilly",
    "4992": "Chapel Street",
    # Sheffield
    "148":  "Fargate",
    "476":  "Division Street",
    "432":  "The Moor",
    "389":  "West Street",
    "2096": "The Wicker",
    # Edinburgh
    "56":   "New Town",
    "95":   "Royal Mile",
    "112":  "Tollcross",
    "146":  "St James Quarter",
    "224":  "Broughton",
    "234":  "Newington",
    "246":  "Leith",
    "331":  "Nicolson Street",
    "361":  "Grassmarket & Victoria Street",
    "388":  "West End",
    "580":  "Dalry",
    "983":  "Haymarket",
    # Glasgow
    "28":   "Buchanan Street",
    "43":   "Sauchiehall Street",
    "123":  "Merchant City",
    "225":  "St Enoch",
    "400":  "Charing Cross",
    "650":  "Finnieston",
    "1131": "Gallowgate",
    "1974": "Bothwell Street",
    "2909": "Glasgow Cross",
    "4201": "George Street",
    # Leeds
    "44":   "Briggate",
    "60":   "Kirkgate Market",
    "365":  "Merrion Centre",
    "378":  "Park Row",
    "1144": "Millennium Square",
    "2337": "Granary Wharf",
    "4677": "St Peter's Square",
    # Birmingham
    "185":  "Colmore Row",
    "198":  "Grand Central",
    "204":  "Southside",
    "207":  "Bullring",
    "657":  "The Mailbox",
    "708":  "Custard Factory",
    "1494": "Newhall Street",
    "2135": "Paradise",
    "3900": "Digbeth",
    # Bristol
    "99":   "Broadmead",
    "139":  "Old City",
    "232":  "Park Street",
    "1953": "King Street",
    "4461": "Park Row",
    # Newcastle
    "125":  "Eldon Square",
    "156":  "Northumberland Street",
    "209":  "Grey Street",
    "221":  "Grainger Town",
    # Norwich
    "103":  "The Lanes",
    "386":  "Tombland",
    "387":  "Castle Mall",
    "658":  "Chapelfield",
    "958":  "Magdalen Street",
    "2241": "St Benedicts",
    # Nottingham
    "77":   "Bridlesmith Gate",
    "157":  "Victoria Centre",
    "212":  "Old Market Square",
    "779":  "Hockley",
    "1325": "Mansfield Road",
    "2101": "Broadmarsh",
    # Aberdeen
    "213":  "Belmont Street",
    "260":  "Holburn Street",
    "494":  "Union Street",
    "576":  "George Street",
    "975":  "Union Square",
    "1030": "Castlegate",
    "1670": "Rosemount",
    # Leicester
    "82":   "Highcross",
    "418":  "Granby Street",
    "597":  "Market Street",
    "623":  "Haymarket",
    "1594": "Belgrave Gate",
    "3941": "Abbey Street",
    # York
    "29":   "Stonegate & Shambles",
    "620":  "Micklegate",
    "1004": "Gillygate & Bootham",
    "1324": "Walmgate",
    "1657": "Goodramgate",
    # Bath
    "88":   "Milsom Street",
    "277":  "Walcot Street",
    "317":  "Southgate",
    "2612": "Green Park",
    # Brighton
    "15":   "The Lanes",
    "32":   "North Laine",
    "109":  "Western Road",
    "178":  "Church Road, Hove",
    "261":  "Kemptown",
    "283":  "London Road",
    "1536": "St George's Road",
}

MANUAL_SUBAREA_NAMES_V2 = {
    # Liverpool
    "97":   "Liverpool ONE",
    "90":   "Bold Street & Ropewalks",
    "288":  "Commercial District",
    "193":  "Church Street & St John's",
    "548":  "Georgian Quarter & Hope Street",
    # Manchester
    "17":   "Northern Quarter",
    "34":   "Deansgate & St Ann's Square",
    "92":   "Arndale & Exchange Square",
    "175":  "Chinatown & Gay Village",
    "332":  "Spinningfields",
    "436":  "St Peter's Square & Oxford Road",
    "750":  "Piccadilly & Ancoats",
    "4992": "Chapel Wharf",
    # Sheffield
    "148":  "Fargate & High Street",
    "476":  "Devonshire Quarter",
    "432":  "The Moor",
    "389":  "West Street & University",
    "2096": "The Wicker",
    # Edinburgh
    "56":   "New Town",
    "95":   "Royal Mile & Old Town",
    "112":  "Tollcross & Bruntsfield",
    "146":  "St James Quarter",
    "224":  "Broughton & Leith Walk",
    "234":  "Newington & Clerk Street",
    "246":  "Leith",
    "331":  "University & Nicolson Street",
    "361":  "Grassmarket & Victoria Street",
    "388":  "West End",
    "580":  "Dalry",
    "983":  "Haymarket",
    # Glasgow
    "28":   "Buchanan Street & Royal Exchange",
    "43":   "Sauchiehall Street & Buchanan Galleries",
    "123":  "Merchant City",
    "225":  "St Enoch & Argyle Street",
    "400":  "Charing Cross",
    "650":  "Finnieston",
    "1131": "Gallowgate & Calton",
    "1974": "Blythswood",
    "2909": "Glasgow Cross",
    "4201": "George Street",
    # Leeds
    "44":   "Briggate & Trinity",
    "60":   "Kirkgate Market & Vicar Lane",
    "365":  "Merrion Centre & The Headrow",
    "378":  "Park Row & City Square",
    "1144": "Millennium Square",
    "2337": "Granary Wharf",
    "4677": "St Peter's Square",
    # Birmingham
    "185":  "Colmore Row & Cathedral Quarter",
    "198":  "Grand Central & New Street",
    "204":  "Southside & Chinese Quarter",
    "207":  "Bullring & Selfridges",
    "657":  "The Mailbox & Brindleyplace",
    "708":  "Custard Factory & Digbeth Creative Quarter",
    "1494": "Jewellery Quarter",
    "2135": "Paradise & Centenary Square",
    "3900": "Digbeth",
    # Bristol
    "99":   "Broadmead & Cabot Circus",
    "139":  "Old City & Christmas Steps",
    "232":  "Park Street & Clifton Triangle",
    "1953": "King Street & Queen Square",
    "4461": "Park Row",
    # Newcastle
    "125":  "Eldon Square",
    "156":  "Northumberland Street",
    "209":  "Grey Street & Quayside",
    "221":  "Grainger Town & Chinatown",
    # Norwich
    "103":  "The Lanes & Royal Arcade",
    "386":  "Tombland & Elm Hill",
    "387":  "Castle Mall & Market",
    "658":  "Chapelfield & Chantry Place",
    "958":  "Magdalen Street & Anglia Square",
    "2241": "St Benedicts",
    # Nottingham
    "77":   "Bridlesmith Gate & Wheeler Gate",
    "157":  "Victoria Centre",
    "212":  "Old Market Square",
    "779":  "Hockley & Lace Market",
    "1325": "Mansfield Road",
    "2101": "Broadmarsh",
    # Aberdeen
    "213":  "Belmont Street & Bon Accord",
    "260":  "Holburn & West End",
    "494":  "Union Street & Trinity Centre",
    "576":  "George Street",
    "975":  "Union Square",
    "1030": "Castlegate",
    "1670": "Rosemount",
    # Leicester
    "82":   "Highcross & Market Place",
    "418":  "Cultural Quarter & Granby Street",
    "597":  "Market & Town Hall Square",
    "623":  "Haymarket & Humberstone Gate",
    "1594": "Belgrave Gate",
    "3941": "St Margaret's",
    # York
    "29":   "Stonegate & Shambles",
    "620":  "Micklegate",
    "1004": "Gillygate & Bootham",
    "1324": "Walmgate",
    "1657": "Goodramgate",
    # Bath
    "88":   "Milsom Street & Bath Street",
    "277":  "Walcot & Artisan Quarter",
    "317":  "Southgate & Stall Street",
    "2612": "Green Park",
    # Brighton
    "15":   "The Lanes",
    "32":   "North Laine",
    "109":  "Western Road & Churchill Square",
    "178":  "Church Road, Hove",
    "261":  "Kemptown",
    "283":  "London Road & Open Market",
    "1536": "St George's Road",
}

# V3: web-verified geography + POI data — proper quarter/neighbourhood names
MANUAL_SUBAREA_NAMES_V3 = {
    # Liverpool (verified: visitliverpool.com neighbourhood map)
    "97":   "Liverpool ONE & Cavern Quarter",
    "90":   "Ropewalks",
    "288":  "Commercial District",
    "193":  "St George's Quarter",
    "548":  "Georgian Quarter",
    # Manchester (verified: MCC regeneration areas + unlockmanchester.com)
    "17":   "Northern Quarter",
    "34":   "St Ann's Square & King Street",
    "92":   "Arndale & Exchange Square",
    "175":  "Chinatown & Gay Village",
    "332":  "Spinningfields",
    "436":  "Petersfield & St Peter's Square",
    "750":  "Piccadilly Basin",
    "4992": "NOMA",
    # Sheffield (verified: sheffieldcitycentre.com quarters)
    "148":  "Cathedral Quarter",
    "476":  "Heart of the City",
    "432":  "The Moor",
    "389":  "Devonshire Quarter",
    "2096": "The Wicker",
    # Edinburgh (verified: edinburgh.org neighbourhoods)
    "56":   "New Town",
    "95":   "Royal Mile & Old Town",
    "112":  "Tollcross",
    "146":  "St James Quarter",
    "224":  "Broughton",
    "234":  "Newington",
    "246":  "Leith",
    "331":  "Southside",
    "361":  "Grassmarket",
    "388":  "West End",
    "580":  "Dalry",
    "983":  "Haymarket",
    # Glasgow (verified: glasgowcitycentrestrategy.com districts)
    "28":   "Buchanan Street",
    "43":   "Sauchiehall Street & Garnethill",
    "123":  "Merchant City",
    "225":  "St Enoch",
    "400":  "Charing Cross",
    "650":  "Finnieston",
    "1131": "Gallowgate & Calton",
    "1974": "Blythswood",
    "2909": "Townhead",
    "4201": "George Street",
    # Leeds (verified: leeds city centre Wikipedia + council docs)
    "44":   "Briggate & Trinity",
    "60":   "Kirkgate Market & Vicar Lane",
    "365":  "Merrion Centre & The Headrow",
    "378":  "Financial Quarter & Park Row",
    "1144": "Civic Quarter & Millennium Square",
    "2337": "Granary Wharf",
    "4677": "Quarry Hill",
    # Birmingham (verified: birmingham.gov.uk + BIDs)
    "185":  "Colmore Business District",
    "198":  "Grand Central & New Street",
    "204":  "Southside & Chinatown",
    "207":  "Bullring",
    "657":  "The Mailbox & Westside",
    "708":  "Digbeth East",
    "1494": "Jewellery Quarter",
    "2135": "Paradise & Centenary Square",
    "3900": "Digbeth",
    # Bristol (verified: 365bristol.com + bristolshoppingquarter.co.uk)
    "99":   "Broadmead & Cabot Circus",
    "139":  "Old City",
    "232":  "Park Street & Clifton Triangle",
    "1953": "King Street & Queen Square",
    "4461": "Park Row",
    # Newcastle (verified: Grainger Town heritage area + wikipedia)
    "125":  "Eldon Square",
    "156":  "Northumberland Street",
    "209":  "Grey Street & Quayside",
    "221":  "Grainger Town & Chinatown",
    # Norwich (verified: cathedralquarternorwich.co.uk + council docs)
    "103":  "The Lanes",
    "386":  "Cathedral Quarter & Tombland",
    "387":  "Castle Mall",
    "658":  "St Stephens & Chapelfield",
    "958":  "Magdalen Street",
    "2241": "St Benedicts",
    # Nottingham (verified: visit-nottinghamshire.co.uk + conservation areas)
    "77":   "Old Market Square",
    "157":  "Victoria Centre",
    "212":  "Castle Quarter",
    "779":  "Hockley & Lace Market",
    "1325": "Mansfield Road",
    "2101": "Broadmarsh & Station",
    # Aberdeen (verified: wikipedia + aberdeen.gov.uk conservation areas)
    "213":  "Belmont Street & Bon Accord",
    "260":  "Holburn & West End",
    "494":  "Union Street",
    "576":  "George Street",
    "975":  "Union Square",
    "1030": "Castlegate",
    "1670": "Rosemount",
    # Leicester (verified: visitleicester.info + council conservation areas)
    "82":   "Highcross & Market Place",
    "418":  "Cultural Quarter",
    "597":  "Old Town & The Lanes",
    "623":  "Haymarket",
    "1594": "Belgrave Gate",
    "3941": "St Margaret's",
    # York (verified: york areas wikipedia)
    "29":   "Stonegate & Shambles",
    "620":  "Micklegate",
    "1004": "Gillygate & Bootham",
    "1324": "Walmgate",
    "1657": "Goodramgate",
    # Bath (verified: visitbath.co.uk + BANES council)
    "88":   "Milsom Quarter",
    "277":  "Walcot & Artisan Quarter",
    "317":  "Southgate",
    "2612": "Green Park",
    # Brighton (verified: wikipedia + neighbourhood guides)
    "15":   "The Lanes",
    "32":   "North Laine",
    "109":  "Western Road",
    "178":  "Hove",
    "261":  "Kemptown",
    "283":  "London Road",
    "1536": "East Kemptown",
}

# V4: POI address-weighted + web-verified blend — street names where POI
# data is strongly dominant, quarter/neighbourhood names where POI is
# dispersed and a well-known area name exists. Non-London sub-areas only.
MANUAL_SUBAREA_NAMES_V4 = {
    # Edinburgh — POI address data + edinburgh.org neighbourhoods
    "56":   "George Street",              # POI: George St 20%, Rose St 14%
    "95":   "Royal Mile",                 # POI: High St 15% (=Royal Mile)
    "112":  "Tollcross",                  # POI: Lothian Rd 14%, Home St 10%. OS=Tollcross
    "146":  "St James Quarter",           # POI: St James Quarter 11%, Princes St 9%
    "224":  "Broughton Street & Elm Row",  # POI: Broughton St 15%, Elm Row 14%
    "234":  "Clerk Street",               # POI: South Clerk St 18%, Clerk St 16%
    "246":  "Leith Walk",                 # POI: Leith Walk 31%, Great Junction St 21%
    "331":  "Nicolson Street",            # POI: Nicolson St 19%, Forrest Rd 14%
    "361":  "Grassmarket",                # POI: Victoria St 11%. Well-known quarter name
    "388":  "West End",                   # POI: Queensferry St 16%. OS=West End
    "580":  "Dalry Road",                 # POI: Dalry Rd 57%
    "983":  "Haymarket",                  # POI: Morrison St 49%. Haymarket more recognisable
    # Brighton — POI address data + neighbourhood guides
    "15":   "The Lanes",                  # POI dispersed (8%). Well-known area name
    "32":   "North Laine",                # POI dispersed (10%). Well-known area name
    "109":  "Western Road",               # POI: Western Rd 46%
    "178":  "Church Road, Hove",          # POI: Church Rd 38%, George St 18%
    "261":  "St James's Street",          # POI: St James's St 26%
    "283":  "London Road",                # POI: London Rd 30%
    "1536": "St George's Road",           # POI: St Georges Rd 47%
    # Manchester — POI address data + MCC regeneration areas
    "17":   "Northern Quarter",           # POI dispersed (8%). Well-known quarter
    "34":   "Deansgate & King Street",    # POI: Deansgate 11%, King St 10%
    "92":   "Arndale & Market Street",    # POI: Arndale Centre 11%, Market St 9%
    "175":  "Chinatown & Gay Village",    # POI: Princess St 13%, Portland St 12%. Quarter names better
    "332":  "Spinningfields",             # POI: Deansgate 23%. Well-known quarter
    "436":  "Oxford Street",              # POI: Oxford St 16%, Oxford Rd 10%
    "750":  "Piccadilly Basin",           # POI: Ducie St 21%, Great Ancoats St 19%. OS=Ancoats
    "4992": "Chapel Street",              # POI: Chapel St 50%
    # Glasgow — POI address data + glasgowcitycentrestrategy.com
    "28":   "Buchanan Street",            # POI: Buchanan St 11%
    "43":   "Sauchiehall Street & Bath Street",  # POI: Sauchiehall St 21%, Bath St 18%
    "123":  "Merchant City",              # POI: Trongate 11%. OS=Merchant City
    "225":  "Argyle Street",              # POI: Argyle St 17%. OS=St Enochs
    "400":  "Charing Cross",              # POI: Sauchiehall St 27%. Well-known junction/area
    "650":  "Finnieston",                 # POI: Argyle St 61%. OS=Finnieston, well-known neighbourhood
    "1131": "Gallowgate",                 # POI: Gallowgate 53%
    "1974": "Bothwell Street",            # POI: Bothwell St 33%, Waterloo St 13%
    "2909": "High Street",                # POI: High St 70%, Duke St 18%
    "4201": "George Street",              # POI: George St 77%
    # Leeds — POI address data + council docs
    "44":   "Albion Street & Briggate",    # POI: Albion St 9%, Briggate 8%
    "60":   "Kirkgate Market & Vicar Lane",  # POI: New Briggate 9%, Vicar Lane 8%
    "365":  "Merrion Centre & The Headrow",  # POI: The Light 13%, The Headrow 12%
    "378":  "Park Row",                   # POI: Wellington St 8%, Park Row 5%
    "1144": "Millennium Square",          # POI: Great George St 38%. Landmark more recognisable
    "2337": "Granary Wharf",              # POI: Dark Neville St 11%, Granary Wharf 11%
    "4677": "St Peter's Square",          # POI str1: St Peter's Square 18%. OS=Quarry Hill
    # Liverpool — POI address data + visitliverpool.com
    "97":   "Liverpool ONE & Cavern Quarter",  # POI: Lord St 8%, Mathew St, Paradise St 7%
    "90":   "Bold Street & Ropewalks",    # POI: Bold St 23%
    "288":  "Commercial District",        # POI: Castle St 11%, Old Hall St 7%
    "193":  "Church Street & St John's",   # POI: Church St, Ranelagh St, St John's Shopping Centre, Clayton Square
    "548":  "Hope Street & Georgian Quarter",  # POI: Rodney St 27%, Hope St 16%
    # Birmingham — POI address data + birmingham.gov.uk BIDs
    "185":  "Colmore Row",                # POI: Corporation St 13%, Colmore Row 9%
    "198":  "Grand Central & New Street", # POI: New St 12%, Grand Central 6%
    "204":  "Hurst Street",               # POI: Hurst St 19%
    "207":  "Bullring",                   # POI: Bullring 10%, High St 6%
    "657":  "The Mailbox",                # POI: Wharfside St 22%, The Mailbox 13%
    "708":  "Custard Factory",            # POI: Gibb St 22%, Custard Factory 7%. OS=Deritend
    "1494": "Jewellery Quarter",          # POI: Newhall St 26%. Well-known quarter
    "2135": "Paradise",                   # POI: Paradise Forum 13%, Paradise Pl 13%
    "3900": "Digbeth",                    # POI: Digbeth 32%. OS=Digbeth
    # Nottingham — POI address data + visit-nottinghamshire.co.uk
    "77":   "Old Market Square",          # POI dispersed (4%). Central square landmark
    "157":  "Victoria Centre",            # POI: Victoria Centre 12%
    "212":  "Castle Quarter",             # POI: Friar Lane 13%. Quarter name recognised
    "779":  "Hockley & Lace Market",      # POI dispersed. OS=Lace Market
    "1325": "Mansfield Road",             # POI: Mansfield Rd 63%
    "2101": "Carrington Street",          # POI: Carrington St 57%, Station St 14%
    # Newcastle — POI address data + Grainger Town heritage area
    "125":  "Eldon Square",               # POI: Eldon Square 9%, Grainger St 8%
    "156":  "Northumberland Street",      # POI: Northumberland St 19%
    "209":  "Grey Street & Mosley Street",  # POI: Grey St 8%, Mosley St 7%
    "221":  "Grainger Town",              # POI: Clayton St 12%, Westgate Rd 9%. Quarter name
    # Bristol — POI address data + bristolshoppingquarter.co.uk
    "99":   "Broadmead",                  # POI: Broadmead 11%, Cabot Circus 5%
    "139":  "Old City",                   # POI: Baldwin St 13%, Corn St 7%. Quarter name
    "232":  "Park Street",                # POI: Park St 26%, Queens Rd 13%
    "1953": "King Street",                # POI: King St 33%, Welsh Back 12%
    "4461": "Park Row",                   # POI: Park Row 48%
    # Aberdeen — POI address data + aberdeen.gov.uk
    "213":  "Belmont Street",             # POI: Union St 14% but 494 is Union St. str2=Belmont St
    "260":  "Holburn Street",             # POI: Holburn St 28%
    "494":  "Union Street",               # POI: Union St 31%
    "576":  "George Street",              # POI: George St 63%
    "975":  "Union Square",               # POI: Union Square 25%
    "1030": "King Street",                # POI: King St 47%
    "1670": "Rosemount",                  # POI: Rosemount Viaduct 54%. Neighbourhood name cleaner
    # Norwich — POI address data + cathedralquarternorwich.co.uk
    "103":  "The Lanes",                  # POI: London St 10%. Well-known Norwich brand
    "386":  "Prince of Wales Road",       # POI: Prince of Wales Rd 20%, Tombland 10%
    "387":  "Castle Mall",                # POI: Castle Mall 14%
    "658":  "St Stephens Street",         # POI: St Stephens St 18%
    "958":  "Magdalen Street",            # POI: Magdalen St 65%
    "2241": "St Benedicts Street",        # POI: St Benedicts St 67%
    # Leicester — POI address data + visitleicester.info
    "82":   "Highcross",                  # POI dispersed (9%). Major shopping centre
    "418":  "Granby Street",              # POI: Granby St 34%
    "597":  "Market Street",              # POI: Market St 18%, Belvoir St 13%
    "623":  "Humberstone Gate",           # POI: Humberstone Gate 20%
    "1594": "Belgrave Gate",              # POI: Belgrave Gate 28%
    "3941": "Abbey Street",               # POI: Abbey St 41%
    # York — POI address data
    "29":   "City Centre",                # POI dispersed (6%). Dominant sub-area
    "620":  "Micklegate",                 # POI: Micklegate 35%
    "1004": "Gillygate",                  # POI: Gillygate 51%, Bootham 18%
    "1324": "Walmgate",                   # POI: Walmgate 54%
    "1657": "Goodramgate",                # POI: Goodramgate 71%
    # Bath — POI address data + visitbath.co.uk
    "88":   "Milsom Street & Westgate Street",  # POI: Milsom St 7%, Westgate St 7%
    "277":  "Walcot Street",              # POI: Walcot St 19%
    "317":  "Southgate",                  # POI dispersed (6%). Shopping centre name
    "2612": "Green Park Station",         # POI: Green Park Station 35%
    # Sheffield — POI address data + sheffieldcitycentre.com
    "148":  "Fargate & Cathedral Quarter",  # POI: High St 6%, Fargate 5%. Blend street + quarter
    "476":  "Division Street",            # POI: Pinstone St 12%, Division St 8%
    "432":  "The Moor",                   # POI: The Moor 34%
    "389":  "West Street & Devonshire Street",  # POI: West St 23%, Devonshire St 22%
    "2096": "The Wicker",                 # POI: Wicker 54%
}


# ─── Shopping Outlets (hardcoded from R code) ─────────────────────────
SHOPPING_OUTLETS = [
    ("Regional Shopping Centre", "Westfield London", 51.50769, -0.22088),
    ("Regional Shopping Centre", "Metrocentre", 54.95721, -1.66745),
    ("Regional Shopping Centre", "Trafford Centre", 53.46510, -2.34764),
    ("Regional Shopping Centre", "Westfield Stratford City", 51.54426, -0.00433),
    ("Regional Shopping Centre", "Bluewater", 51.43912, 0.27160),
    ("Regional Shopping Centre", "intu Merry Hill", 52.48139, -2.11066),
    ("Regional Shopping Centre", "Lakeside Shopping Centre", 51.48941, 0.28538),
    ("Regional Shopping Centre", "Meadowhall", 53.41411, -1.41112),
    ("Regional Shopping Centre", "East Kilbride Shopping Centre", 55.76021, -4.17709),
    ("Regional Shopping Centre", "Silverburn Centre", 55.82113, -4.34125),
    ("Regional Shopping Centre", "intu Braehead", 55.87600, -4.36464),
    ("Regional Shopping Centre", "White Rose Centre", 53.75868, -1.57349),
    ("Large Outlet Shopping Centre", "Ashford Designer Outlet", 51.13739, 0.88017),
    ("Large Outlet Shopping Centre", "Astle Park West Bromwich", 52.52010, -1.99603),
    ("Large Outlet Shopping Centre", "Bicester Outlet Village", 51.89238, -1.15608),
    ("Large Outlet Shopping Centre", "Bideford Atlantic Village", 51.00756, -4.23733),
    ("Large Outlet Shopping Centre", "Burberry Factory Outlet London", 51.54651, -0.05093),
    ("Large Outlet Shopping Centre", "Castleford Junction 32 Outlet", 53.71246, -1.33884),
    ("Large Outlet Shopping Centre", "Chatham Dockside Outlet Centre", 51.40160, 0.53771),
    ("Large Outlet Shopping Centre", "Cheshire Oaks Designer Outlet", 53.26539, -2.88090),
    ("Large Outlet Shopping Centre", "Clacton Factory Outlet", 51.81859, 1.16821),
    ("Large Outlet Shopping Centre", "Clarks Village Outlet Somerset", 51.12833, -2.74159),
    ("Large Outlet Shopping Centre", "Dalton Park Outlet", 54.81537, -1.37392),
    ("Large Outlet Shopping Centre", "Doncaster Lakeside Village", 53.50769, -1.11360),
    ("Large Outlet Shopping Centre", "Dover De Bradelei Wharf Outlet", 51.12211, 1.31417),
    ("Large Outlet Shopping Centre", "East Midlands Outlet Junction 28", 53.10808, -1.31266),
    ("Large Outlet Shopping Centre", "Freeport Braintree", 51.87007, 0.57148),
    ("Large Outlet Shopping Centre", "Freeport Fleetwood Outlet", 53.91786, -3.01185),
    ("Large Outlet Shopping Centre", "Freeport Talke Stoke-on-Trent", 53.07060, -2.26308),
    ("Large Outlet Shopping Centre", "Gloucester Quays Outlet", 51.85953, -2.25162),
    ("Large Outlet Shopping Centre", "Hertfordshire Galleria Outlet Shopping", 51.76141, -0.24022),
    ("Large Outlet Shopping Centre", "Hornsea Freeport Outlet", 53.89849, -0.17242),
    ("Large Outlet Shopping Centre", "Kilver Court Designer Village", 51.19064, -2.53532),
    ("Large Outlet Shopping Centre", "London Designer Outlet Wembley", 51.55647, -0.28320),
    ("Large Outlet Shopping Centre", "Lowry Outlet Salford Quays", 53.47092, -2.29251),
    ("Large Outlet Shopping Centre", "Newcastle Royal Quays Outlet", 54.99533, -1.46428),
    ("Large Outlet Shopping Centre", "Portsmouth Gunwharf Quays", 50.79546, -1.10382),
    ("Large Outlet Shopping Centre", "Springfields Spalding Outlet", 52.79944, -0.12633),
    ("Large Outlet Shopping Centre", "Swindon Designer Outlet", 51.56272, -1.79719),
    ("Large Outlet Shopping Centre", "The Mill Outlet Batley", 53.71292, -1.62513),
    ("Large Outlet Shopping Centre", "York Designer Outlet", 53.92233, -1.07687),
    ("Large Outlet Shopping Centre", "Banbridge Village Outlet", 54.33172, -6.27615),
    ("Large Outlet Shopping Centre", "Cribbs Causeway", 51.52455, -2.59552),
    ("Large Outlet Shopping Centre", "Bridgend Designer Outlets Wales", 51.53241, -3.57684),
    ("Large Outlet Shopping Centre", "Gretna Gateway Outlet Village", 54.99688, -3.05652),
    ("Large Outlet Shopping Centre", "Livingston Designer Outlet", 55.88311, -3.52014),
    ("Large Outlet Shopping Centre", "Sterling Mills Outlet", 56.14927, -3.74005),
    ("Large Shopping Centre", "Salford Shopping Centre", 53.48880, -2.28913),
]


def load_data():
    """Load retail centres and lookup CSVs."""
    print("Loading retail centres...")
    rc = gpd.read_file(GPKG_PATH).to_crs(CRS_BNG)
    rc["RC_ID"] = rc["RC_ID"].astype(str)

    lookups = {}
    for name in ["RC_Naming_ONS", "RC_Naming_OS", "RC_Naming_OS_Internal", "RC_Naming_Streets", "RC_Naming_OSM_RetailParks", "RC_Naming_OSM_Neighbourhoods"]:
        path = os.path.join(EXPORTS_DIR, f"{name}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path, dtype={"RC_ID": str})
            lookups[name] = df
            print(f"  Loaded {name}: {len(df)} rows")
        else:
            print(f"  WARNING: {path} not found")
            lookups[name] = pd.DataFrame({"RC_ID": rc["RC_ID"]})

    return rc, lookups


def match_outlets_to_centres(rc):
    """Match hardcoded shopping outlet coordinates to RC_IDs."""
    outlets = pd.DataFrame(SHOPPING_OUTLETS, columns=["SubType", "Name", "Lat", "Lon"])
    outlets_gdf = gpd.GeoDataFrame(
        outlets,
        geometry=gpd.points_from_xy(outlets["Lon"], outlets["Lat"]),
        crs="EPSG:4326",
    ).to_crs(CRS_BNG)

    # Spatial join to find which centre each outlet falls in
    matched = gpd.sjoin(outlets_gdf, rc[["RC_ID", "geometry"]], how="left", predicate="within")
    matched = matched[matched["RC_ID"].notna()]
    return matched[["SubType", "Name", "RC_ID"]].drop_duplicates("Name")


def assemble_name_components(components, include_parentheses=True):
    """
    Assemble name from components: [street, neighbourhood, la, region, country].
    Format: Street; Neighbourhood; LA (Region; Country)
    """
    street, neighbourhood, la, region, country = [
        str(c) if pd.notna(c) and str(c).strip() else "" for c in components
    ]

    parts = []
    if street:
        parts.append(street)
    if neighbourhood:
        parts.append(neighbourhood)
    if la:
        parts.append(la)

    if include_parentheses and (region or country):
        region_country = "; ".join(filter(None, [region, country]))
        if region_country:
            parts.append(f"({region_country})")

    name = "; ".join(parts)
    return name


def clean_name(name):
    """Apply all name cleanup rules."""
    if pd.isna(name) or not name:
        return name

    # Collapse repeated separators
    while "; ; " in name:
        name = name.replace("; ; ", "; ")

    # Remove leading/trailing separators
    name = name.strip("; ")

    # Fix country duplication
    name = name.replace("Scotland; Scotland", "Scotland")
    name = name.replace("Wales; Wales", "Wales")
    name = name.replace("Northern Ireland; Northern Ireland", "Northern Ireland")

    # Fix "; (" -> " ("
    name = name.replace("; (", " (")

    # Fix LA inversions
    name = name.replace("Bristol, City of", "City of Bristol")
    name = name.replace("Kingston upon Hull, City of", "City of Kingston upon Hull")
    name = name.replace("Herefordshire, County of", "County of Herefordshire")

    return name


def generate_names():
    """Main name generation pipeline."""
    rc, lookups = load_data()

    ons = lookups["RC_Naming_ONS"]
    os_nearest = lookups["RC_Naming_OS"]
    os_internal = lookups["RC_Naming_OS_Internal"]
    streets = lookups["RC_Naming_Streets"]
    osm_rp = lookups["RC_Naming_OSM_RetailParks"]
    osm_nbhd = lookups["RC_Naming_OSM_Neighbourhoods"]

    # ─── Classification: use what's in the gpkg ────────────────────
    print("\n=== 2a. Classification ===")
    classification = rc[["RC_ID", "Classification"]].copy()
    print(f"  Classifications:\n{classification['Classification'].value_counts().to_string()}")

    # Match shopping outlets
    outlets = match_outlets_to_centres(rc)
    print(f"  Matched {len(outlets)} shopping outlets to centres")

    # Override classification for matched outlets
    for _, row in outlets.iterrows():
        mask = classification["RC_ID"] == row["RC_ID"]
        if mask.any():
            classification.loc[mask, "Classification"] = row["SubType"]

    # ─── Level 1: Street Name ──────────────────────────────────────
    print("\n=== 2b. Name Assembly ===")
    print("  Level 1: Street names...")
    level1 = streets[["RC_ID"]].copy()
    level1["Street"] = None

    if "Str_1" in streets.columns and "Str_1_P" in streets.columns:
        str1 = streets["Str_1"]
        str1_p = pd.to_numeric(streets["Str_1_P"], errors="coerce")
        str2 = streets.get("Str_2", pd.Series(dtype=str))
        str2_p = pd.to_numeric(streets.get("Str_2_P", pd.Series(dtype=float)), errors="coerce")

        # 31% threshold: if top street > 31%, use alone; else combine top two
        level1["Street"] = np.where(
            str1_p > 0.31,
            str1.astype(str),
            np.where(
                str2_p > 0.31,
                str1.astype(str) + " & " + str2.astype(str),
                None,
            ),
        )
        # Clean up 'nan' strings
        level1.loc[level1["Street"].isin(["nan", "None", "nan & nan"]), "Street"] = None
        # Title case
        level1["Street"] = level1["Street"].apply(
            lambda x: x.title() if pd.notna(x) else x
        )

    # ─── Level 2: Neighbourhood (OS place name) ───────────────────
    print("  Level 2: Neighbourhood names...")

    # From OS nearest: pick type with minimum distance
    level2 = os_nearest[["RC_ID"]].copy()
    level2["nearest"] = None

    dist_cols = {}
    name_cols = {}
    for short in ["City", "Town", "Village", "Suburban", "Settlement", "Hamlet"]:
        if short in os_nearest.columns:
            name_cols[short] = short
        if f"{short}D" in os_nearest.columns:
            dist_cols[short] = f"{short}D"

    if dist_cols:
        # Find minimum distance type for each centre
        dist_df = os_nearest[list(dist_cols.values())].apply(pd.to_numeric, errors="coerce")
        min_type = dist_df.idxmin(axis=1)  # Column name of minimum distance

        for i, (idx, mt) in enumerate(min_type.items()):
            if pd.notna(mt):
                short = mt.replace("D", "")
                if short in os_nearest.columns:
                    val = os_nearest.loc[idx, short]
                    if pd.notna(val):
                        level2.loc[idx, "nearest"] = val

    # Override with internal names where available (prefer internal)
    # Build internal pick independently using priority chain (like R code),
    # then override nearest wherever internal has a value.
    if "RC_ID" in os_internal.columns:
        merged = level2.merge(os_internal, on="RC_ID", how="left")
        merged["inner"] = None
        for ptype in ["City", "Village", "Town", "Suburban", "Settlement", "Hamlet"]:
            if ptype not in merged.columns:
                continue
            has_value = merged[ptype].notna() & (merged[ptype].str.strip() != "")
            not_yet_set = merged["inner"].isna()
            merged.loc[has_value & not_yet_set, "inner"] = (
                merged.loc[has_value & not_yet_set, ptype].str.split(";").str[0].str.strip()
            )
        # Override nearest with internal pick where available
        has_inner = merged["inner"].notna()
        merged.loc[has_inner, "nearest"] = merged.loc[has_inner, "inner"]
        level2["nearest"] = merged["nearest"]

    # OSM neighbourhood/quarter names — fallback where OS internal has no match
    if "OSM_NbhdName" in osm_nbhd.columns:
        osm_matched = osm_nbhd[osm_nbhd["OSM_NbhdName"].notna()].copy()
        osm_count = 0
        for _, row in osm_matched.iterrows():
            mask = level2["RC_ID"] == row["RC_ID"]
            if not mask.any():
                continue
            # Only use OSM name where OS internal didn't provide one
            current = level2.loc[mask, "nearest"].iloc[0]
            os_row = os_internal[os_internal["RC_ID"] == row["RC_ID"]]
            has_os_internal = False
            if len(os_row) > 0:
                for ptype in ["City", "Village", "Town", "Suburban", "Settlement", "Hamlet"]:
                    if ptype in os_row.columns:
                        v = os_row.iloc[0].get(ptype)
                        if pd.notna(v) and str(v).strip():
                            has_os_internal = True
                            break
            if not has_os_internal:
                level2.loc[mask, "nearest"] = row["OSM_NbhdName"]
                osm_count += 1
        print(f"  OSM neighbourhood fallback applied: {osm_count} centres")

    # Manual neighbourhood overrides (fix junk OS Settlement names)
    NEIGHBOURHOOD_OVERRIDES = {
        "2126": "Paternoster Row",  # was "Orchard Square" (a named courtyard in Sheffield)
    }
    for rc_id, name in NEIGHBOURHOOD_OVERRIDES.items():
        level2.loc[level2["RC_ID"] == rc_id, "nearest"] = name

    # NI centres: OS Open Names doesn't cover NI. Use settlement name
    # for large centres (like OS City/Town), SDZ for smaller ones (like
    # OS Suburban/Village). Fallback to whichever is available.
    ni_ids = rc.loc[rc["RegionName"].isin(["NI", "Northern Ireland"]), "RC_ID"].tolist()
    large_classes = {"Regional Centre", "Major Town Centre", "Town Centre"}
    if ni_ids:
        # Clear OS-derived names for NI centres
        level2.loc[level2["RC_ID"].isin(ni_ids), "nearest"] = None

        for rc_id in ni_ids:
            cls = rc.loc[rc["RC_ID"] == rc_id, "Classification"]
            is_large = len(cls) > 0 and cls.iloc[0] in large_classes
            name = None

            # Primary source based on size
            if is_large and "CityNM_1" in ons.columns:
                city = ons.loc[ons["RC_ID"] == rc_id, "CityNM_1"]
                if len(city) > 0 and pd.notna(city.iloc[0]) and str(city.iloc[0]).strip():
                    name = str(city.iloc[0]).strip().title()
            elif not is_large and "NbhdNM_1" in ons.columns:
                nbhd = ons.loc[ons["RC_ID"] == rc_id, "NbhdNM_1"]
                if len(nbhd) > 0 and pd.notna(nbhd.iloc[0]):
                    name = re.sub(r"_[A-Z]$|_*\d+", "", str(nbhd.iloc[0])).replace("_", " ").strip()

            # Fallback to the other source
            if name is None and "CityNM_1" in ons.columns:
                city = ons.loc[ons["RC_ID"] == rc_id, "CityNM_1"]
                if len(city) > 0 and pd.notna(city.iloc[0]) and str(city.iloc[0]).strip():
                    name = str(city.iloc[0]).strip().title()
            if name is None and "NbhdNM_1" in ons.columns:
                nbhd = ons.loc[ons["RC_ID"] == rc_id, "NbhdNM_1"]
                if len(nbhd) > 0 and pd.notna(nbhd.iloc[0]):
                    name = re.sub(r"_[A-Z]$|_*\d+", "", str(nbhd.iloc[0])).replace("_", " ").strip()

            if name:
                level2.loc[level2["RC_ID"] == rc_id, "nearest"] = name

    # ─── Merge and assemble final names ────────────────────────────
    print("  Assembling final names...")

    naming = rc[["RC_ID"]].copy()

    # Get LA, Region, Country from ONS lookup or pre-joined columns
    if "LocalAuthorityNM_1" in ons.columns:
        naming = naming.merge(ons[["RC_ID", "LocalAuthorityNM_1", "Country", "RegionNM"]].drop_duplicates("RC_ID"),
                              on="RC_ID", how="left")
    else:
        naming["LocalAuthorityNM_1"] = rc["LocalAuthorityNM_1"].values
        naming["Country"] = rc.get("Country", "").values if "Country" in rc.columns else ""
        naming["RegionNM"] = rc["RegionName"].values

    # Fill country/region if missing
    if naming["Country"].isna().any() or (naming["Country"] == "").any():
        region_map = rc.set_index("RC_ID")["RegionName"]
        for idx in naming.index:
            if pd.isna(naming.loc[idx, "Country"]) or naming.loc[idx, "Country"] == "":
                rc_id = naming.loc[idx, "RC_ID"]
                rgn = region_map.get(rc_id, "")
                if rgn in ["North East", "North West", "Yorkshire and The Humber",
                           "East Midlands", "West Midlands", "East of England",
                           "London", "South East", "South West"]:
                    naming.loc[idx, "Country"] = "England"
                    naming.loc[idx, "RegionNM"] = rgn
                elif rgn == "Wales":
                    naming.loc[idx, "Country"] = "Wales"
                    naming.loc[idx, "RegionNM"] = "Wales"
                elif rgn == "Scotland":
                    naming.loc[idx, "Country"] = "Scotland"
                    naming.loc[idx, "RegionNM"] = "Scotland"
                elif rgn in ("Northern Ireland", "NI"):
                    naming.loc[idx, "Country"] = "Northern Ireland"
                    naming.loc[idx, "RegionNM"] = "Northern Ireland"

    naming = naming.merge(classification, on="RC_ID", how="left")
    naming = naming.merge(level1[["RC_ID", "Street"]], on="RC_ID", how="left")
    naming = naming.merge(level2[["RC_ID", "nearest"]].rename(columns={"nearest": "Neighbourhood"}),
                          on="RC_ID", how="left")

    # Track sub-areas so they always get street names
    subarea_ids = set(rc.loc[rc["was_split"] == True, "RC_ID"].tolist())

    # Assemble names based on classification
    naming["RC_Name"] = ""

    for idx in naming.index:
        cls = naming.loc[idx, "Classification"]
        street = naming.loc[idx, "Street"]
        nbhd = naming.loc[idx, "Neighbourhood"]
        la = naming.loc[idx, "LocalAuthorityNM_1"]
        region = naming.loc[idx, "RegionNM"]
        country = naming.loc[idx, "Country"]
        is_subarea = naming.loc[idx, "RC_ID"] in subarea_ids

        if cls in ("Regional Centre", "Major Town Centre", "Town Centre") and not is_subarea:
            # No street — Neighbourhood; LA (Region; Country)
            name = assemble_name_components([None, nbhd, la, region, country])
        else:
            # Street; Neighbourhood; LA (Region; Country)
            name = assemble_name_components([street, nbhd, la, region, country])

        naming.loc[idx, "RC_Name"] = name

    # ─── Retail park naming ────────────────────────────────────────
    # Priority: 1) OSM landuse name  2) Foursquare branded  3) street-based + "Retail Park"
    print("  Retail park naming...")
    rp_mask = naming["Classification"].isin(["Large Retail Park", "Small Retail Park"])
    if rp_mask.any():
        # Track which parks got a proper name
        rp_named = set()

        # 1) OSM landuse names (first choice)
        if "OSM_RetailParkName" in osm_rp.columns:
            for _, row in osm_rp[osm_rp["OSM_RetailParkName"].notna()].iterrows():
                mask = (naming["RC_ID"] == row["RC_ID"]) & rp_mask
                if not mask.any():
                    continue
                la = naming.loc[mask, "LocalAuthorityNM_1"].iloc[0]
                region = naming.loc[mask, "RegionNM"].iloc[0]
                country = naming.loc[mask, "Country"].iloc[0]
                naming.loc[mask, "RC_Name"] = assemble_name_components(
                    [None, row["OSM_RetailParkName"], la, region, country]
                )
                rp_named.add(row["RC_ID"])
            print(f"    OSM named: {len(rp_named)} retail parks")

        # 2) Foursquare branded names (fallback for parks without OSM name)
        rp_cols = ["RC_ID"]
        for col in ["RetailParkBranded", "RetailParkLocality"]:
            if col in streets.columns:
                rp_cols.append(col)
        rp_info = streets[rp_cols].copy()

        fsq_count = 0
        for _, row in rp_info.iterrows():
            if row["RC_ID"] in rp_named:
                continue  # already named by OSM
            mask = (naming["RC_ID"] == row["RC_ID"]) & rp_mask
            if not mask.any():
                continue
            branded = row.get("RetailParkBranded")
            if pd.notna(branded):
                la = naming.loc[mask, "LocalAuthorityNM_1"].iloc[0]
                region = naming.loc[mask, "RegionNM"].iloc[0]
                country = naming.loc[mask, "Country"].iloc[0]
                naming.loc[mask, "RC_Name"] = assemble_name_components(
                    [None, branded, la, region, country]
                )
                rp_named.add(row["RC_ID"])
                fsq_count += 1
        print(f"    Foursquare branded: {fsq_count} retail parks")

    # 3) Append "Retail Park" to first name component for remaining retail parks
    for idx in naming[rp_mask].index:
        rc_id = naming.loc[idx, "RC_ID"]
        if rc_id in rp_named:
            continue  # already has a proper name
        name = naming.loc[idx, "RC_Name"]
        parts = name.split("; ")
        if parts:
            parts[0] = parts[0].strip() + " Retail Park"
            naming.loc[idx, "RC_Name"] = "; ".join(p.strip() for p in parts)

    # Manual retail park overrides
    naming.loc[naming["RC_ID"] == "3379", "RC_Name"] = naming.loc[naming["RC_ID"] == "3379", "RC_Name"].str.replace("Europa Boulevard Retail Park", "Gemini Retail Park")

    # ─── Shopping centre / outlet naming ───────────────────────────
    print("  Shopping centre naming...")
    outlets = match_outlets_to_centres(rc)
    for _, row in outlets.iterrows():
        mask = naming["RC_ID"] == row["RC_ID"]
        if mask.any():
            la = naming.loc[mask, "LocalAuthorityNM_1"].iloc[0]
            region = naming.loc[mask, "RegionNM"].iloc[0]
            country = naming.loc[mask, "Country"].iloc[0]
            naming.loc[mask, "RC_Name"] = assemble_name_components(
                [None, row["Name"], la, region, country]
            )

    # ─── Sub-area naming ──────────────────────────────────────────
    # Parent_ID is a group number, NOT an RC_ID. First build a "parent"
    # name for each group (the joined centre), then give each sub-area
    # its own name using its local neighbourhood prefixed to the parent name.
    print("\n=== 2c. Sub-area Naming ===")
    sub_areas = rc[rc["was_split"] == True][["RC_ID", "Parent_ID", "tr_retailN"]].copy()
    sub_areas["Parent_ID"] = sub_areas["Parent_ID"].astype(int).astype(str)
    sub_areas["tr_retailN"] = pd.to_numeric(sub_areas["tr_retailN"], errors="coerce").fillna(0)
    print(f"  {len(sub_areas)} sub-areas across {sub_areas['Parent_ID'].nunique()} parent groups")

    for _, group in sub_areas.groupby("Parent_ID"):
        member_ids = group["RC_ID"].tolist()

        # Determine the parent centre name: use the City-type OS name from
        # the group (closest City across all members), falling back to Town
        city_name = None
        best_dist = float("inf")
        for mid in member_ids:
            row = os_nearest[os_nearest["RC_ID"] == mid]
            if len(row) == 0:
                continue
            for ptype in ["City", "Town"]:
                dcol = f"{ptype}D"
                if ptype in row.columns and dcol in row.columns:
                    d = pd.to_numeric(row.iloc[0][dcol], errors="coerce")
                    nm = row.iloc[0][ptype]
                    if pd.notna(d) and d < best_dist and pd.notna(nm):
                        best_dist = d
                        city_name = str(nm).split(";")[0].strip()
                        if city_name == "City of London":
                            city_name = "London"

        # Primary sub-area = highest retail count
        primary_rc_id = group.sort_values("tr_retailN", ascending=False).iloc[0]["RC_ID"]
        primary_mask = naming["RC_ID"] == primary_rc_id
        if not primary_mask.any():
            continue

        # Build parent location from primary sub-area
        la = naming.loc[primary_mask, "LocalAuthorityNM_1"].iloc[0]
        region = naming.loc[primary_mask, "RegionNM"].iloc[0]
        country = naming.loc[primary_mask, "Country"].iloc[0]

        # Determine if this is a London group
        is_london = (city_name == "London" or region == "London")
        if is_london:
            la = "London"
            city_name = "London"

        # London: include OS Settlement name for context, UNLESS the group
        # contains a Regional Centre (i.e. the big central London group)
        group_classes = set(
            naming.loc[naming["RC_ID"].isin(member_ids), "Classification"].dropna()
        )
        london_show_settlement = is_london and "Regional Centre" not in group_classes

        for mid in member_ids:
            mask = naming["RC_ID"] == mid
            if not mask.any():
                continue

            manual_names = {
                "v1": MANUAL_SUBAREA_NAMES_V1,
                "v2": MANUAL_SUBAREA_NAMES_V2,
                "v3": MANUAL_SUBAREA_NAMES_V3,
                "v4": MANUAL_SUBAREA_NAMES_V4,
            }.get(MANUAL_SUBAREA_VERSION, {})
            if mid in manual_names:
                local_name = manual_names[mid]
            else:
                existing_name = naming.loc[mask, "RC_Name"].iloc[0]
                local_name = existing_name.split(";", 1)[0].strip()

            if not city_name:
                continue

            if is_london:
                if london_show_settlement:
                    # e.g. "Upper Street (Islington); London (London; England)"
                    settlement = None
                    os_row = os_nearest[os_nearest["RC_ID"] == mid]
                    if len(os_row) > 0 and "Settlement" in os_row.columns:
                        s = os_row.iloc[0]["Settlement"]
                        if pd.notna(s):
                            settlement = str(s).split(";")[0].strip()
                    if settlement:
                        nbhd = f"{local_name} ({settlement})"
                    else:
                        nbhd = local_name
                else:
                    # e.g. "Mayfair; London (London; England)"
                    nbhd = local_name
                naming.loc[mask, "RC_Name"] = assemble_name_components(
                    [None, nbhd, "London", "London", "England"]
                )
            else:
                # e.g. "Northern Quarter (Manchester City Centre); Manchester (North West; England)"
                nbhd = f"{local_name} ({city_name} City Centre)"
                naming.loc[mask, "RC_Name"] = assemble_name_components(
                    [None, nbhd, la, region, country]
                )

    # ─── Cleanup ──────────────────────────────────────────────────
    print("\n=== 2d. Cleanup & Deduplication ===")
    naming["RC_Name"] = naming["RC_Name"].apply(clean_name)

    # Handle empty names
    naming.loc[naming["RC_Name"].isna() | (naming["RC_Name"] == ""), "RC_Name"] = (
        naming.loc[naming["RC_Name"].isna() | (naming["RC_Name"] == ""), "LocalAuthorityNM_1"]
    )

    # Deduplicate: append " - 2", " - 3" etc.
    # Sort by classification hierarchy so higher-ranked centres keep the clean name
    class_priority = {
        "Regional Centre": 0, "Major Town Centre": 1, "Town Centre": 2,
        "Market Town": 3, "District Centre": 4, "Local Centre": 5,
        "Small Local Centre": 6, "Large Retail Park": 7, "Small Retail Park": 8,
        "Large Shopping Centre": 9, "Small Shopping Centre": 10,
    }
    name_counts = naming["RC_Name"].value_counts()
    duplicates = name_counts[name_counts > 1].index.tolist()

    for dup_name in duplicates:
        dup_mask = naming["RC_Name"] == dup_name
        dup_rows = naming.loc[dup_mask].copy()
        dup_rows["_class_priority"] = dup_rows["Classification"].map(class_priority).fillna(99)
        dup_indices = dup_rows.sort_values("_class_priority").index.tolist()
        # First (highest-ranked) keeps original name
        for i, idx in enumerate(dup_indices[1:], start=1):
            naming.loc[idx, "RC_Name"] = f"{dup_name} - {i}"

    # ─── Export ────────────────────────────────────────────────────
    print("\n=== 2e. Export ===")
    os.makedirs(EXPORTS_DIR, exist_ok=True)

    # CSV lookup
    csv_cols = ["RC_ID", "Street", "Neighbourhood", "LocalAuthorityNM_1",
                "RegionNM", "Country", "RC_Name", "Classification"]
    csv_out = naming[[c for c in csv_cols if c in naming.columns]].copy()
    csv_path = os.path.join(EXPORTS_DIR, "rc2025_naming_lookup.csv")
    csv_out.to_csv(csv_path, index=False)
    print(f"  Saved: {csv_path}")

    # GeoPackage
    rc_named = rc.merge(naming[["RC_ID", "RC_Name"]], on="RC_ID", how="left")
    gpkg_path = os.path.join(EXPORTS_DIR, "rc2025_named.gpkg")
    rc_named.to_file(gpkg_path, driver="GPKG")
    print(f"  Saved: {gpkg_path}")

    # GeoParquet
    parquet_path = os.path.join(EXPORTS_DIR, "rc2025_named.parquet")
    rc_named.to_parquet(parquet_path)
    print(f"  Saved: {parquet_path}")

    # Summary
    print(f"\n=== Complete ===")
    print(f"  Total centres named: {naming['RC_Name'].notna().sum()} / {len(naming)}")
    print(f"  Unique names: {naming['RC_Name'].nunique()}")

    # Spot-check: show some Regional Centres
    regional = naming[naming["Classification"] == "Regional Centre"]["RC_Name"].head(10)
    if len(regional) > 0:
        print(f"\n  Sample Regional Centres:")
        for name in regional:
            print(f"    {name}")

    # Show some retail parks
    rps = naming[naming["Classification"].isin(["Large Retail Park", "Small Retail Park"])]["RC_Name"].head(5)
    if len(rps) > 0:
        print(f"\n  Sample Retail Parks:")
        for name in rps:
            print(f"    {name}")

    return naming


if __name__ == "__main__":
    generate_names()
