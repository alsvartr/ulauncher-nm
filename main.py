import os
import json
import logging
from time import sleep
import time

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.SmallResultItem import SmallResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.RunScriptAction import RunScriptAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction

logging.basicConfig()
logger = logging.getLogger(__name__)

global usage_cache, profile_cache
usage_cache = {}
profile_cache = {}

# Check if nmcli is present
nmcli = os.popen("which nmcli").read().rstrip()
if nmcli == "":
	logger.error("nmcli executable was not found!")
	exit()

# Init usage tracking file
script_directory = os.path.dirname(os.path.realpath(__file__))
usage_db = os.path.join(script_directory, "usage.json")
if os.path.exists(usage_db):
    with open(usage_db, 'r') as db:
        raw = db.read()
        usage_cache = json.loads(raw)

# Init profiles cache (because NM is very slow on getting details about VPN profiles)
profile_db = os.path.join(script_directory, "profiles.json")
if os.path.exists(profile_db):
    with open(profile_db, 'r') as db:
        raw = db.read()
        profile_cache = json.loads(raw)

class NMExtension(Extension):
    def __init__(self):

        super(NMExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())

    def list_vpn(self, query):
	global profiles, profile_cache
	profiles = dict()
        items_cache = []

        try:
		vpns = os.popen('nmcli -t connection show | grep vpn').read().rstrip()
		vpns = vpns.split("\n")

		for v in vpns:
			vpn = v.split(":")
			profiles[vpn[1]] = vpn[0]
        except Exception as e:
		logger.error("Failed to get VPN profiles")

	types = dict()
	has_new = False
	for p in profiles:
		# First check profiles cache, if not in cache - get details from NM
		if profile_cache.has_key(p):
			type = profile_cache[p]
		else:
			type = con_details(p)
			has_new = True

		types[p] = type
		desc = type
		name = profiles[p]

		if os.path.exists("images/%s.svg" % type):
			icon = type
		else:
			icon = "vpn"

		if (query in name.lower()) or (query in desc.lower()):
			items_cache.append(create_item(name, desc, icon, {"mod": "vpn", "name": p}))

	items_cache = sorted(items_cache, key=sort_by_usage, reverse=True)

	# Write VPN details to cache file if we have uncached profiles
	if has_new == True:
		with open(profile_db, 'w') as db:
			db.write(json.dumps(types, indent=2))
		with open(profile_db, 'r') as db:
			raw = db.read()
			profile_cache = json.loads(raw)

	return items_cache

    def list_settings(self, query):
	global profiles
	profiles = dict()
	items = []

	profiles[0] = dict(name="Disable WIFI", desc="disable wifi adapters")
	profiles[1] = dict(name="Enable WIFI", desc="enable wifi adapters")
	profiles[2] = dict(name="Disable networking", desc="disable all network adapters")
	profiles[3] = dict(name="Enable networking", desc="enable network adapters")
	profiles[4] = dict(name="Rescan WIFI", desc="search to wifi networks nearby")

	try:
		state = os.popen("nmcli -t general status").read().rstrip()
		state = state.split(":")
        except Exception as e:
		logger.error("Failed to get NM general status")

	if (state[3] == "enabled") and (query in profiles[0]["name"].lower()):
		items.append(create_item(profiles[0]["name"], profiles[0]["desc"], "wifi-disable", {"mod": "settings", "name": "disable_wifi"}))
	if (state[3] == "disabled") and (query in profiles[1]["name"].lower()):
		items.append(create_item(profiles[1]["name"], profiles[1]["desc"], "wifi-enable", {"mod": "settings", "name": "enable_wifi"}))
	if (state[0] != "asleep") and (query in profiles[2]["name"].lower()):
		items.append(create_item(profiles[2]["name"], profiles[2]["desc"], "network-disable", {"mod": "settings", "name": "disable_net"}))
	if (state[0] == "asleep") and (query in profiles[3]["name"].lower()):
		items.append(create_item(profiles[3]["name"], profiles[3]["desc"], "network-enable", {"mod": "settings", "name": "enable_net"}))

	if query in profiles[4]["name"].lower():
		items.append(create_item(profiles[4]["name"], profiles[4]["desc"], "wifi-rescan", {"mod": "settings", "name": "rescan_wifi"}))

	return items

    def list_wifi(self, query):
	global profiles, last_scan
	profiles = dict()
	items_cache = []
	dt = int(time.time())

	try:
		last_scan
	except NameError:
		last_scan = dt-300

	try:
		if dt - last_scan > 120:
			os.popen("nmcli device wifi rescan")
			sleep(int(self.preferences["rescan_wait"]))
			last_scan = dt

		wifis = os.popen('nmcli -t device wifi list').read().rstrip()
		wifis = wifis.split("\n")

		for w in wifis:
			wifi = w.split(":")
			name = wifi[1]
			speed = wifi[4]
			signal = wifi[5]
			security = wifi[7]
			if int(signal) > 70:
				icon = "wifi-n3"
			if (int(signal) > 30) and (int(signal) < 70):
				icon = "wifi-n2"
			if int(signal) < 30:
				icon = "wifi-n1"
			profiles[name] = name

			desc = "Speed: %s, Security: %s, Signal: %s" % (speed, security, signal)

			if (query in name.lower()) or (query in desc.lower()):
				items_cache.append(create_item(name, desc, icon, {"mod": "wifi", "name": name}))
        except Exception as e:
		logger.error("Failed to get WIFI networks")


	items_cache = sorted(items_cache, key=sort_by_usage, reverse=True)
	return items_cache

    def list_all(self, query):
	items = []

	vpns = self.list_vpn(query)
	wifis = self.list_wifi(query)
	settings = self.list_settings(query)
	for w in wifis:
		items.append(w)
	for v in vpns:
		items.append(v)
	for s in settings:
		items.append(s)
	return items

class KeywordQueryEventListener(EventListener):
    def on_event(self, event, extension):
	keyword = event.get_keyword()

	if keyword == extension.preferences["nm"]:
		term = (event.get_argument() or "").lower()
		profiles_list = extension.list_all(term)
		return RenderResultListAction(profiles_list[:15])

	if keyword == extension.preferences["nms"]:
		term = (event.get_argument() or "").lower()
		profiles_list = extension.list_settings(term)
		return RenderResultListAction(profiles_list[:8])

	if keyword == extension.preferences["nm-vpn"]:
		term = (event.get_argument() or "").lower()
		profiles_list = extension.list_vpn(term)
		return RenderResultListAction(profiles_list[:8])

	if keyword == extension.preferences["nm-wifi"]:
		term = (event.get_argument() or "").lower()
		profiles_list = extension.list_wifi(term)
		return RenderResultListAction(profiles_list[:8])


class ItemEnterEventListener(EventListener):
    def on_event(self, event, extension):
	global usage_cache

        data = event.get_data()
	mod = data["mod"]
        on_enter = data["name"]

	if (mod == "settings"):
		if on_enter == "disable_wifi":
			os.popen("nmcli radio wifi off")
		if on_enter == "enable_wifi":
			os.popen("nmcli radio wifi on")
		if on_enter == "disable_net":
			os.popen("nmcli networking off")
		if on_enter == "enable_net":
			os.popen("nmcli networking on")
		if on_enter == "rescan_wifi":
			os.popen("nmcli device wifi rescan")
		return 0

	if (mod == "wifi") or (mod == "vpn"):
		state = os.popen("nmcli -g GENERAL.STATE connection show \"%s\"" % on_enter).read().rstrip()
		if state == "activated":
			return os.popen("nmcli connection down \"%s\"" % on_enter)

		if on_enter in usage_cache:
			usage_cache[on_enter] = usage_cache[on_enter]+1
		else:
			usage_cache[on_enter] = 1

		with open(usage_db, 'w') as db:
			db.write(json.dumps(usage_cache, indent=2))

		return os.popen("nmcli connection up \"%s\"" % on_enter)


def create_item(name, description, icon, on_enter):
	return ExtensionResultItem(
		name=name,
		description=description,
		icon="images/{}.svg".format(icon),
		on_enter=ExtensionCustomAction(
			on_enter)
		)


def sort_by_usage(i):
	global profiles, usage_cache

	for p in profiles:
		if profiles[p] == i._name:
			j = p

	# Return score according to usage
	if j in usage_cache:
		return usage_cache[j]
	# Default is 0 (no usage rank / unused)
	return 0

def con_details(con):
	try:
		type = os.popen("nmcli -g vpn.service-type connection show %s" % con).read()
		type = type.split(".")
		type = type[-1].rstrip()
        except Exception as e:
		logger.error("Failed to get VPN details")

	return type

if __name__ == "__main__":
	NMExtension().run()
