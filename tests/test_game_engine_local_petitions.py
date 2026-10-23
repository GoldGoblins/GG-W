"""Physical paid-charter transitions and narrow recoverable consent proofs."""
import copy
import unittest
import json
from unittest.mock import patch

from backend import game_engine_items as items
from backend.game_engine_adapter_social import guild_record
from backend.game_engine_local_custody import asset_id, digest
from backend.game_engine_local_custody import RecoveryRequired
from backend.game_engine_local_characters import CharacterStore, atomic
from backend import game_engine_local_petitions as petitions
from tests import test_game_engine_local_custody as fixture

A, B, C = fixture.A, fixture.B, fixture.C
D = 'd' * 32


class PetitionTransitions(unittest.TestCase):
    setUp = fixture.Custody.setUp
    seed = fixture.Custody.seed

    def setup_charter(self, *, owner=A, signers=None, item_id='charter-1'):
        value = self.store.snapshot()
        characters = value['characters']
        characters[D] = copy.deepcopy(characters[C])
        characters[D]['payload']['character_appearance'] = {'own_character': D}
        item = items.make_instance(self.catalog, item_id, 'item.guild_charter')
        item['petition'] = dict(title='Actual Saved Guild', owner='player', max_signatures=3,
                                signers=list(signers or []))
        characters[owner]['payload']['item_instances'].append(item)
        characters[owner]['payload']['inventory'] = items.inventory_counts(characters[owner]['payload']['item_instances'])
        self.characters = characters; self.shared = value['shared']
        self.names = {key: 'Actual ' + key[:1].upper() for key in characters}
        self.owner = owner; self.asset = asset_id(owner, item); self.terms = petitions.terms(owner, item)
        return item

    def row(self, op, **fields):
        return dict(dict(op=op, owner=self.owner, asset=self.asset, terms=self.terms), **fields)

    def transition(self, issuer, sequence, row, *, now=100.):
        before_characters = copy.deepcopy(self.characters); before_shared = copy.deepcopy(self.shared)
        before_assets, before_money = self.store._validate(before_characters, before_shared)
        result = petitions.apply(self.characters, self.shared, issuer, sequence, row, now=now, names=self.names)
        petitions.validate(self.characters, self.shared)
        after_assets, after_money = self.store._validate(self.characters, self.shared)
        petitions.prove(before_assets, after_assets, before_characters, self.characters,
            before_shared, self.shared, issuer, sequence, dict(op='PETITION_ACTION', row=row), self.asset, names=self.names)
        self.assertEqual(before_assets, after_assets)
        self.assertEqual(before_money, after_money)
        return result

    def offer(self, target=B, sequence=1, now=100.):
        return self.transition(self.owner, sequence, self.row('PetitionOffer', target=target), now=now)['offer']

    def sign(self, target=B, sequence=1, now=101.):
        return self.transition(target, sequence, self.row('PetitionSign', offer=self.shared['petition_offers'][target]['id']), now=now)

    def test_offer_is_reference_only_and_requires_actual_recipient_consent(self):
        self.setup_charter(); before = copy.deepcopy(self.characters)
        self.offer()
        self.assertEqual(self.characters, before)
        self.assertEqual(self.shared['petition_offers'][B]['expires'], 160.)
        self.assertEqual(petitions.charter(self.characters[A]['payload'], A, self.asset)['petition']['signers'], [])
        self.sign()
        self.assertEqual(petitions.charter(self.characters[A]['payload'], A, self.asset)['petition']['signers'], [B])
        self.assertEqual(self.shared['petition_offers'], {})
        self.assertFalse(any(i['definition_id'] == 'item.guild_charter' for i in self.characters[B]['payload']['item_instances']))

    def test_identical_local_charter_ids_resolve_exact_owner_asset(self):
        first = self.setup_charter()
        other = copy.deepcopy(first)
        self.characters[B]['payload']['item_instances'].append(other)
        self.characters[B]['payload']['inventory'] = items.inventory_counts(self.characters[B]['payload']['item_instances'])
        self.assertNotEqual(asset_id(A, first), asset_id(B, other))
        self.offer(); self.sign()
        self.assertEqual(other['petition']['signers'], [])
        self.assertEqual(first['petition']['signers'], [B])

    def test_terms_exclude_mutable_signers_so_pending_independent_offers_remain_valid(self):
        item = self.setup_charter()
        self.offer(B, 1); self.offer(C, 2); self.offer(D, 3)
        self.sign(B); self.sign(C); self.sign(D)
        self.assertEqual(item['petition']['signers'], [B, C, D])
        self.assertEqual(petitions.terms(A, item), self.terms)

    def test_paid_charter_turn_in_consumes_exact_item_and_creates_same_shared_guild_without_second_fee(self):
        item = self.setup_charter(signers=[B, C, D]); before_money = self.store._validate(self.characters, self.shared)[1]
        result = self.transition(A, 4, self.row('PetitionTurnIn'))
        self.assertEqual(set(self.shared['guilds'][result['guild']]['members']), {A, B, C, D})
        self.assertEqual(self.shared['guilds'][result['guild']]['leader'], A)
        self.assertNotIn(item, self.characters[A]['payload']['item_instances'])
        self.assertEqual(self.store._validate(self.characters, self.shared)[1], before_money)
        self.assertEqual(self.shared['money_sinks'], 0)

    def test_turn_in_rechecks_saved_signer_shared_and_original_npc_guild_membership(self):
        for local in (False, True):
            self.setup_charter(signers=[B, C, D])
            if local:
                self.characters[B]['payload'].setdefault('player', {}).setdefault('client_controls', {}).setdefault('services', {})['guild'] = guild_record('Actual NPC Guild')
            else:
                guild = guild_record('Other Guild', leader=B); guild['leader'] = B
                self.shared['guilds']['other'] = guild
            with self.assertRaisesRegex(ValueError, 'SIGNER_UNAVAILABLE'):
                petitions.apply(self.characters, self.shared, A, 1, self.row('PetitionTurnIn'), now=100.)

    def test_rename_resets_real_signatures_and_all_old_terms_offers(self):
        item = self.setup_charter(signers=[B]); self.offer(C)
        old_terms = self.terms
        self.transition(A, 2, self.row('PetitionRename', name='Renamed Actual Guild'))
        self.assertEqual(item['petition']['signers'], [])
        self.assertEqual(self.shared['petition_offers'], {})
        self.assertNotEqual(petitions.terms(A, item), old_terms)
        with self.assertRaisesRegex(ValueError, 'TERMS_CHANGED'):
            petitions.apply(self.characters, self.shared, C, 1, self.row('PetitionSign', offer='petition-' + '1' * 32), now=101.)

    def test_close_declines_without_signing_and_expiry_never_auto_signs(self):
        item = self.setup_charter(); offer = self.offer()
        self.transition(B, 1, self.row('PetitionClose', offer=offer))
        self.assertEqual(item['petition']['signers'], [])
        self.offer(sequence=2)
        self.shared['clock'] = 161.; petitions.prune(self.shared)
        self.assertEqual(self.shared['petition_offers'], {})
        self.assertEqual(item['petition']['signers'], [])

    def test_stale_offer_and_wrong_recipient_cannot_sign(self):
        self.setup_charter(); offer = self.offer()
        for recipient, key, now in ((C, offer, 101.), (B, 'petition-' + '0' * 32, 101.), (B, offer, 161.)):
            with self.assertRaisesRegex(ValueError, 'OFFER_CHANGED_OR_EXPIRED'):
                petitions.apply(copy.deepcopy(self.characters), copy.deepcopy(self.shared), recipient, 1,
                                self.row('PetitionSign', offer=key), now=now)

    def test_mixed_npc_shared_signatures_rejected_but_owner_can_explicitly_reset(self):
        item = self.setup_charter(signers=['npc-wanderer-01'])
        with self.assertRaisesRegex(ValueError, 'MIXED_SIGNATURES'):self.offer()
        self.transition(A, 2, self.row('PetitionRename', name='Start Saved Consent'))
        self.assertEqual(item['petition']['signers'], [])
        self.terms = petitions.terms(A, item)
        self.offer(sequence=3)

    def test_ignored_owner_cannot_send_actual_recipient_offer(self):
        self.setup_charter()
        self.characters[B]['payload'].setdefault('player', {}).setdefault('client_controls', {}).setdefault('local_client', {})['ignores'] = [self.names[A].lower()]
        with self.assertRaisesRegex(ValueError, 'TARGET_IGNORES'):self.offer()

    def test_offer_pending_is_bounded_and_duplicate_signature_rejected(self):
        self.setup_charter(); self.offer()
        with self.assertRaisesRegex(ValueError, 'OFFER_PENDING'):self.offer(sequence=2)
        self.sign()
        with self.assertRaisesRegex(ValueError, 'ALREADY_SIGNED_OR_FULL'):self.offer(sequence=3)

    def test_delete_guard_covers_live_offer_and_actual_saved_signature_references(self):
        self.setup_charter(); self.offer()
        self.assertEqual(petitions.delete_blockers(A, self.characters, self.shared), ['PETITION_OFFER'])
        self.assertEqual(petitions.delete_blockers(B, self.characters, self.shared), ['PETITION_OFFER'])
        self.sign()
        self.assertEqual(petitions.delete_blockers(A, self.characters, self.shared), ['PETITION_SIGNATURE'])
        self.assertEqual(petitions.delete_blockers(B, self.characters, self.shared), ['PETITION_SIGNATURE'])
        self.assertEqual(petitions.delete_blockers(C, self.characters, self.shared), [])

    def test_explicit_destroy_consumes_only_exact_charter_and_cancels_its_offers(self):
        item = self.setup_charter(signers=[B]); self.offer(C)
        result = self.transition(A, 2, self.row('PetitionDestroy'))
        self.assertEqual(result['guild'], '')
        self.assertEqual(self.shared['petition_offers'], {})
        self.assertNotIn(item, self.characters[A]['payload']['item_instances'])
        self.assertEqual(self.shared['guilds'], {})

    def test_proof_rejects_unrelated_actual_item_gear_mutation(self):
        self.setup_charter(); offer = self.offer()
        before = copy.deepcopy(self.characters); old = copy.deepcopy(self.shared)
        row = self.row('PetitionSign', offer=offer)
        petitions.apply(self.characters, self.shared, B, 1, row, now=101.)
        self.characters[A]['payload']['item_instances'][0]['gear_stats'] = {'armor': 999}
        ba = self.store._validate(before, old)[0]; aa = self.store._validate(self.characters, self.shared)[0]
        with self.assertRaisesRegex(ValueError, 'PETITION_ENTITLEMENT'):
            petitions.prove(ba, aa, before, self.characters, old, self.shared, B, 1,
                            dict(op='PETITION_ACTION', row=row), self.asset)

    def test_proof_rejects_unapproved_charter_change_and_wrong_asset_source(self):
        self.setup_charter(); offer = self.offer()
        before = copy.deepcopy(self.characters); old = copy.deepcopy(self.shared)
        row = self.row('PetitionSign', offer=offer)
        petitions.apply(self.characters, self.shared, B, 1, row, now=101.)
        self.characters[A]['payload']['item_instances'][-1]['petition']['signers'].append(C)
        ba = self.store._validate(before, old)[0]; aa = self.store._validate(self.characters, self.shared)[0]
        for source in (self.asset, 'custody-' + '0' * 32):
            with self.assertRaisesRegex(ValueError, 'PETITION_ENTITLEMENT'):
                petitions.prove(dict(ba), aa, before, self.characters, old, self.shared, B, 1,
                                dict(op='PETITION_ACTION', row=row), source)

    def test_exact_transition_proof_rejects_tampered_null_receipt_result(self):
        self.setup_charter(); offer = self.offer()
        before = copy.deepcopy(self.characters); old = copy.deepcopy(self.shared)
        row = self.row('PetitionSign', offer=offer)
        petitions.apply(self.characters, self.shared, B, 1, row, now=101.)
        ba = self.store._validate(before, old)[0]; aa = self.store._validate(self.characters, self.shared)[0]
        with self.assertRaisesRegex(ValueError, 'PETITION_ENTITLEMENT'):
            petitions.prove(ba, aa, before, self.characters, old, self.shared, B, 1,
                            dict(op='PETITION_ACTION', row=row), self.asset, result=None)

    def test_reference_shapes_and_extra_fields_cannot_become_generic_mutation_entitlement(self):
        self.setup_charter()
        for row in (self.row('PetitionRename', name='Okay', invented=True),
                    self.row('PetitionTurnIn', asset='charter-1'), self.row('PetitionOffer', target=True)):
            with self.assertRaises(ValueError):
                petitions.apply(self.characters, self.shared, A, 1, row, now=100.)


class DurablePetitions(unittest.TestCase):
    setUp = fixture.Custody.setUp
    seed = fixture.Custody.seed
    payload = fixture.Custody.payload
    files = fixture.Custody.files

    def charter(self):
        payload = self.payload(A)
        item = items.make_instance(self.catalog, 'charter-1', 'item.guild_charter')
        item['petition'] = dict(title='Durable Actual Guild', owner='player', max_signatures=3, signers=[])
        payload['item_instances'].append(item)
        payload['inventory'] = items.inventory_counts(payload['item_instances'])
        CharacterStore(self.root).save(A, payload)
        self.asset = asset_id(A, item); self.terms = petitions.terms(A, item)
        return item

    def row(self, op, **fields):
        return dict(dict(op=op, owner=A, asset=self.asset, terms=self.terms), **fields)

    def offer(self, recipient=B, sequence=1):
        return self.store.petition_action(A, sequence, self.row('PetitionOffer', target=recipient), now=100.)['result']['offer']

    def test_durable_sign_changes_only_actual_owners_charter_and_exact_replay_has_no_second_write(self):
        self.charter(); offer = self.offer()
        before = self.store.snapshot(); row = self.row('PetitionSign', offer=offer)
        result = self.store.petition_action(B, 1, row, now=101., expected_revision=before['characters'][B]['revision'])
        final = self.store.snapshot()
        item = petitions.charter(final['characters'][A]['payload'], A, self.asset)
        self.assertEqual(item['petition']['signers'], [B])
        self.assertEqual(final['characters'][B]['payload'], before['characters'][B]['payload'])
        disk = self.files()
        replay = self.store.petition_action(B, 1, row, now=999., expected_revision=before['characters'][B]['revision'])
        self.assertTrue(replay['replayed']); self.assertEqual(replay['result'], result['result']); self.assertEqual(disk, self.files())
        with self.assertRaisesRegex(ValueError, 'REPLAY_CHANGED'):
            self.store.petition_action(B, 1, dict(row, offer='petition-' + '0' * 32), now=101., expected_revision=before['characters'][B]['revision'])

    def test_real_two_file_crash_after_owner_write_recovers_forward_and_preserves_recipient_appearance(self):
        self.charter(); offer = self.offer(); before = self.store.snapshot()
        def fault(stage, name):
            if stage == 'replaced' and name == A + '.json':raise OSError('actual owner replace fault')
        self.store.fault = fault
        with self.assertRaises(RecoveryRequired):
            self.store.petition_action(B, 1, self.row('PetitionSign', offer=offer), now=101.,
                                      expected_revision=before['characters'][B]['revision'])
        self.store.fault = None
        self.assertEqual(self.store.recover()['status'], 'COMMITTED')
        final = self.store.snapshot()
        self.assertEqual(petitions.charter(final['characters'][A]['payload'], A, self.asset)['petition']['signers'], [B])
        self.assertEqual(final['characters'][B]['payload']['character_appearance'], {'own_character': B})
        self.assertEqual(final['shared']['petition_offers'], {})

    def test_journal_directory_sync_uncertainty_commits_intent_and_requires_recovery(self):
        self.charter(); before = self.files()
        def fault(stage, name):
            if stage == 'replaced' and name == 'shared-custody.pending.json':raise OSError('directory uncertainty')
        self.store.fault = fault
        with self.assertRaises(RecoveryRequired) as raised:self.offer()
        self.assertTrue(raised.exception.committed)
        self.store.fault = None; self.store.recover()
        self.assertIn(B, self.store.snapshot()['shared']['petition_offers'])
        self.assertNotEqual(before, self.files())

    def test_corrupted_journal_signature_transition_cannot_materialize_unagreed_signature(self):
        self.charter(); offer = self.offer()
        def fault(stage, name):
            if stage == 'replaced' and name == 'shared-custody.pending.json':raise OSError('hold intent')
        self.store.fault = fault
        with self.assertRaises(RecoveryRequired):
            self.store.petition_action(B, 1, self.row('PetitionSign', offer=offer), now=101.)
        self.store.fault = None
        path = self.root / 'shared-custody.pending.json'; journal = json.loads(path.read_text())
        target = next(t for t in journal['targets'] if t['name'] == A + '.json')
        target['value']['payload']['item_instances'][-1]['petition']['signers'].append(C)
        target['after'] = digest(target['value'])
        shared_target = journal['targets'][-1]
        shared_target['value']['receipts'][B + ':1']['after'][A + '.json'] = target['after']
        shared_target['after'] = digest(shared_target['value']); atomic(path, journal)
        with self.assertRaises(RecoveryRequired) as raised:self.store.recover()
        self.assertIn('PETITION_ENTITLEMENT', str(raised.exception.__cause__))
        self.assertEqual(petitions.charter(CharacterStore(self.root).load(A), A, self.asset)['petition']['signers'], [])

    def test_deletion_and_ordinary_save_guard_actual_offer_and_signature_references(self):
        self.charter(); offer = self.offer()
        self.assertIn('PETITION_OFFER', self.store.can_delete(B, include_history=False)['blockers'])
        with self.assertRaisesRegex(ValueError, 'DELETE_REFERENCES'):self.store.delete_character(A)
        broken = self.payload(A); broken['item_instances'] = [i for i in broken['item_instances'] if i['definition_id'] != 'item.guild_charter']
        broken['inventory'] = items.inventory_counts(broken['item_instances'])
        with self.assertRaisesRegex(ValueError, 'ITEM_CHANGED_OR_MISSING'):self.store.validate_save(A, broken)
        self.store.petition_action(B, 1, self.row('PetitionSign', offer=offer), now=101.)
        self.assertIn('PETITION_SIGNATURE', self.store.can_delete(B, include_history=False)['blockers'])
        self.store.petition_action(A, 2, self.row('PetitionDestroy'), now=102.)
        self.assertTrue(self.store.can_delete(B, include_history=False)['allowed'])

    def test_legacy_nonpetition_journal_without_optional_proof_still_recovers(self):
        def fault(stage, name):
            if stage == 'replaced' and name == 'shared-custody.pending.json':raise OSError('hold old intent')
        self.store.fault = fault
        with self.assertRaises(RecoveryRequired):
            self.store.send_mail(A, 1, B, catalog=self.catalog, subject='Legacy exact message')
        self.store.fault = None
        journal = json.loads((self.root / 'shared-custody.pending.json').read_text())
        self.assertNotIn('petition_source', journal)
        self.assertEqual(self.store.recover()['status'], 'COMMITTED')

    def test_settlement_expires_offer_without_signing_or_destroying_paid_charter(self):
        self.charter(); self.offer()
        self.store.settle(A, 2, now=161.)
        self.assertEqual(self.store.snapshot()['shared']['petition_offers'], {})
        self.assertEqual(petitions.charter(self.payload(A), A, self.asset)['petition']['signers'], [])

