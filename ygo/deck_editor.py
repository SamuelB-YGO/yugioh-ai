from collections import OrderedDict, Counter
import json
import random
import natsort

from .card import Card
from . import globals
from . import models
from .constants import *
from .parsers.deck_editor_parser import DeckEditorParser

class DeckEditor:
	def __init__(self, player):
		self.deck_edit_pos = 0
		self.deck_name = ''
		self.last_search = ""
		self.player = player

	def list(self, args):
		decks = self.player.get_account().decks
		if args:
			s = args[0].lower()
			decks = [deck for deck in decks if s in deck.name.lower()]
		if not decks:
			self.player.notify(self.player._("No decks."))
			return
		self.player.notify(self.player._("You own %d decks:")%(len(decks)))
		for deck in decks:

			banlist = None
			
			for b in globals.banlists.values():
				if len(b.check(json.loads(deck.content)['cards'])) == 0:
					banlist = b
					break

			if banlist:
				self.player.notify(self.player._("{0} (compatible with {1} banlist)").format(deck.name, banlist.name))
			else:
				self.player.notify(self.player._("{0} (compatible with no banlist)").format(deck.name))

	def clear(self, name):
		account = self.player.get_account()
		session = self.player.connection.session
		deck = models.Deck.find(session, account, name)
		if not deck:
			self.player.notify(self.player._("Deck not found."))
			return
		deck.content = json.dumps({'cards': []})
		session.commit()
		self.player.notify(self.player._("Deck cleared."))

	def delete(self, name):
		account = self.player.get_account()
		session = self.player.connection.session
		deck = models.Deck.find(session, account, name)
		if not deck:
			self.player.notify(self.player._("Deck not found."))
			return
		session.delete(deck)
		session.commit()
		self.player.notify(self.player._("Deck deleted."))

	def rename(self, args):
		if '=' not in args:
			self.player.notify(self.player._("Usage: deck rename <old>=<new>"))
			return
		args = args.strip().split('=', 1)
		name = args[0].strip()
		dest = args[1].strip()
		if not name or not dest:
			self.player.notify(self.player._("Usage: deck rename <old>=<new>"))
			return
		if '=' in dest:
			self.player.notify(self.player._("Deck names may not contain =."))
			return
		account = self.player.get_account()
		session = self.player.connection.session
		deck = models.Deck.find(session, account, name)
		if not deck:
			self.player.notify(self.player._("Deck not found."))
			return
		dest_deck = models.Deck.find(session, account, dest)
		if dest_deck:
			self.player.notify(self.player._("Destination deck already exists"))
			return
		deck.name = dest
		session.commit()
		self.player.notify(self.player._("Deck renamed."))

	def copy(self, args):
		if '=' not in args:
			self.player.notify(self.player._("Usage: deck copy <old>=<new>"))
			return
		args = args.strip().split('=', 1)
		name = args[0].strip()
		dest = args[1].strip()
		if not name or not dest:
			self.player.notify(self.player._("Usage: deck copy <old>=<new>"))
			return
		if '=' in dest:
			self.player.notify(self.player._("Deck names may not contain =."))
			return

		if '/' in dest:
			self.player.notify(self.player._("The copy destination can only be one of your own decks."))
			return

		player_name = ''
		deck_name = name

		if '/' in deck_name:
			player_name = deck_name.split('/')[0].title()
			deck_name = deck_name[(len(player_name) + 1):]

		if player_name != '':
			if player_name.lower() == self.player.nickname.lower():
				self.player.notify(self.player._("You don't need to mention yourself if you want to use your own deck."))
				return

			account = self.player.connection.session.query(models.Account).filter_by(name=player_name).first()

			if not account:
				self.player.notify(self.player._("Player {0} could not be found.".format(player_name)))
				return
			
		else:
			account = self.player.get_account()

		session = self.player.connection.session

		if player_name != '':
			deck = models.Deck.find_public(session, account, deck_name)
		else:
			deck = models.Deck.find(session, account, name)

		if not deck:
			self.player.notify(self.player._("Deck doesn't exist or isn't publically available."))
			return

		dest_deck = models.Deck.find(session, self.player.get_account(), dest)

		if dest_deck:
			self.player.notify(self.player._("Destination deck already exists"))
			return

		new_deck = models.Deck(name=dest, content=deck.content)
		self.player.get_account().decks.append(new_deck)
		session.commit()
		self.player.notify(self.player._("Deck copied."))

	def draw(self, args):
		if '=' not in args:
			self.player.notify(self.player._("Usage: deck draw <deck>=<number>"))
			return
		args = args.strip().split('=', 1)
		name = args[0].strip()
		amount = int(args[1])
		if not name or not amount:
			self.player.notify(self.player._("Usage: deck draw <deck>=<number>"))
			return
		if name.startswith('public/'):
			account = self.player.connection.session.query(models.Account).filter_by(name='Public').first()
			name = name[7:]
		else:
			account = self.player.get_account()
		session = self.player.connection.session
		deck = models.Deck.find(session, account, name)
		if not deck:
			self.player.notify(self.player._("Deck not found."))
			session.commit()
			return
		cards = json.loads(deck.content)['cards']
		session.commit()
		cards = [c for c in cards if not (Card(c).type & (TYPE_XYZ | TYPE_SYNCHRO | TYPE_FUSION | TYPE_LINK))]
		random.shuffle(cards)
		for i in range(0, min(amount, len(cards))):
			self.player.notify(self.player._("Drew: %s") % Card(cards[i]).get_name(self.player))

	def edit(self, deck_name):
		con = self.player.connection
		account = con.player.get_account()

		deck = models.Deck.find(con.session, account, deck_name)

		if deck.public:
			con.notify(con._("You cannot edit public decks. Switch it back to private by using deck private {0} first.".format(deck_name)))
			return

		con.player.paused_parser = con.parser
		con.parser = DeckEditorParser

		if deck:
			con.notify(con._("Deck exists, loading."))
			con.player.deck = json.loads(deck.content)
			invalid_cards = con.player.get_invalid_cards_in_deck()
			con.player.deck['cards'] = [c for c in con.player.deck['cards'] if c not in invalid_cards]
			if len(invalid_cards):
				con.notify(con._("Invalid cards were removed from this deck. This usually occurs after the server loading a new database which doesn't know those cards anymore."))
		else:
			con.notify(con._("Creating new deck %s.") % deck_name)
		self.deck_name = deck_name
		con.parser.prompt(con)
	
	@staticmethod
	def group_cards(cardlist):
		"""
		Groups all cards in the supplied list.

		This provides output like foo, bar(x3) etc.
		"""
		cnt = Counter(cardlist)
		return OrderedDict(natsort.natsorted(dict(cnt).items()))
	
	def group_sort_cards(self, cardlist):
		"""
		Use the above function to group all cards, then sort them into groups.
		"""
		extras = [c for c in cardlist if (Card(c).type & (TYPE_XYZ | TYPE_SYNCHRO | TYPE_FUSION | TYPE_LINK))]
		for c in extras: cardlist.remove(c)
		traps = [c for c in cardlist if (Card(c).type & 4)]
		for c in traps: cardlist.remove(c)
		monsters = [c for c in cardlist if (Card(c).type&1)]
		for c in monsters: cardlist.remove(c)
		spells = [c for c in cardlist if (Card(c).type & 2)]
		for c in spells: cardlist.remove(c)
		other=cardlist
		extras_group = self.group_cards(extras)
		traps_group = self.group_cards(traps)
		spells_group = self.group_cards(spells)
		monsters_group = self.group_cards(monsters)
		other_group = self.group_cards(other)
		groups=(monsters_group, spells_group, traps_group, extras_group, other_group)
		return groups

	def group_cards_combined(self, cardlist):
		"""
		Groups and sorts cards, then combines them in the correct order for proper indexing.
		"""
		groups = self.group_sort_cards(cardlist)
		monsters, spells, traps, extras, other = groups
		full = OrderedDict()
		for x,y in monsters.items(): full[x] = y
		for x,y in spells.items(): full[x] = y
		for x,y in traps.items(): full[x] = y
		for x,y in extras.items(): full[x] = y
		for x, y in other.items(): full[x] = y
		return full

	def find_next(self, text, start, limit=None, wrapped=False):
		sql = 'SELECT id FROM texts WHERE UPPERCASE(name) LIKE ? and id in (%s) ORDER BY id ASC LIMIT 1'
		if limit:
			cards = globals.server.all_cards[start:start+limit]
		else:
			cards = globals.server.all_cards[start:]
		row = self.player.cdb.execute(sql % (', '.join([str(c) for c in cards])), ('%'+text.upper()+'%', )).fetchone()
		if row is not None:
			return globals.server.all_cards.index(row[0])
		if wrapped:
			return
		return self.find_next(text, 0, start, wrapped=True)

	def find_prev(self, text, start, end=None, wrapped=False):
		sql = 'SELECT id FROM texts WHERE UPPERCASE(name) LIKE ? AND id IN (%s) ORDER BY id DESC LIMIT 1'
		pos = start
		if end is None:
			end = 0
		cards = globals.server.all_cards[end:start]
		row = self.player.cdb.execute(sql % (', '.join([str(c) for c in cards])), ('%'+text.upper()+'%', )).fetchone()
		if row is not None:
			return globals.server.all_cards.index(row[0])
		if wrapped:
			return
		return self.find_prev(text, len(globals.server.all_cards) - 1, start, wrapped=True)

	def save(self):
		deck = json.dumps(self.player.deck)
		session = self.player.connection.session
		account = self.player.get_account()
		existing_deck = models.Deck.find(session, account, self.deck_name)
		if existing_deck:
			new_deck = existing_deck
		else:
			new_deck = models.Deck(account_id=account.id, name=self.deck_name)
			account.decks.append(new_deck)
		new_deck.content = deck
		session.commit()

	def new(self, name):
		account = self.player.get_account()
		session = self.player.connection.session
		deck = models.Deck.find(session, account, name)
		if deck:
			self.player.notify(self.player._("That deck already exists."))
			return
		deck = models.Deck(account_id=account.id, name=name)
		account.decks.append(deck)
		deck.content = json.dumps({'cards': []})
		session.commit()
		self.player.notify(self.player._("Deck created."))

	def check(self, deck, banlist = None):
		con = self.player.connection
		if not banlist:

			self.player.notify(self.player._("The following banlists are available (from newest to oldest):"))

			for k in globals.banlists.keys():
				self.player.notify(k)

			return

		if banlist not in globals.banlists:
			self.player.notify(self.player._("This banlist is unknown."))
			return

		errors = globals.banlists[banlist].check_and_resolve(deck)

		for err in errors:
			self.player.notify(self.player._("%s: limit %d, found %d.") % (err[0].get_name(self.player), err[1], err[2]))

		self.player.notify(self.player._("Check completed with %d errors.") % len(errors))

	def count_occurrence_in_deck(self, code):
		card = Card(code)
		if card.alias == 0:
			possible_cards = globals.language_handler.primary_database.execute('SELECT id FROM datas WHERE id = ? OR alias = ?', (code, code, )).fetchall()
		else:
			possible_cards = globals.language_handler.primary_database.execute('SELECT id FROM datas WHERE id = ? OR alias = ? OR id = ?', (code, card.alias, card.alias, )).fetchall()
		found = 0
		for c in possible_cards:
			found += self.player.deck['cards'].count(c[0])
		return found

	def deck_import(self, args):
		if '=' not in args:
			self.player.notify(self.player._("Usage: deck import <name>=<string>"))
			return
		args = args.strip().split('=', 1)
		name = args[0].strip()
		s = args[1].strip()
		if not name or not s:
			self.player.notify(self.player._("Usage: deck import <name>=<string>"))
			return
		try:
			json.loads(s)
		except ValueError:
			self.player.notify(self.player._("Invalid import string."))
			return
		account = self.player.get_account()
		session = self.player.connection.session
		deck = models.Deck.find(session, account, name)
		if deck:
			self.player.notify(self.player._("Deck already exists."))
			return
		deck = models.Deck(account_id=account.id, name=name, content=s)
		account.decks.append(deck)
		session.commit()
		self.player.notify(self.player._("Deck %s imported.") % name)

	def deck_export(self, args):
		name = args
		account = self.player.get_account()
		session = self.player.connection.session
		deck = models.Deck.find(session, account, name)
		if not deck:
			self.player.notify(self.player._("Deck not found."))
			return
		s = deck.content
		self.player.notify("deck import %s=%s" % (deck.name, s))

	def set_public(self, name, pub):

		account = self.player.get_account()
		session = self.player.connection.session

		deck = models.Deck.find(session, account, name)

		if not deck:
			self.player.notify(self.player._("Deck not found."))
			return

		if deck.public == pub:
			if pub:
				self.player.notify(self.player._("This deck is already public."))
			else:
				self.player.notify(self.player._("This deck is already private."))
			return

		if pub:

			# performing several checks
			# making unfinished decks publically available doesn't make sense

			content = json.loads(deck.content)

			main, extra = self.player.count_deck_cards(content['cards'])

			if main < 40 or main > 60:
				self.player.notify(self.player._("Your main deck must contain between 40 and 60 cards (currently %d).") % main)
				return

			if extra > 15:
				self.player.notify(self.player._("Your extra deck may not contain more than 15 cards (currently %d).")%extra)
				return

		deck.public = pub
		session.commit()

		if pub:
			self.player.notify(self.player._("This deck is now public."))
		else:
			self.player.notify(self.player._("This deck is no longer public."))
