package main

import (
	"bytes"
	"encoding/json"
	"reflect"
	"testing"
)

func boundPolicySource(t *testing.T) DagSource {
	t.Helper()
	base, _ := dagFixture(t)
	source := base.Source
	policy := currentDagExecutionPolicy()
	source.Genesis.Schema = "gg.parallel-dag.genesis.v3"
	source.Genesis.ExecutionPolicy = &policy
	source.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", source.Genesis)
	return source
}

func TestDagExecutionPolicyLegacyCanonicalSourceRetainsOriginalShape(t *testing.T) {
	base, _ := dagFixture(t)
	if validateDagSource(base.Source) != nil || base.Source.Genesis.ExecutionPolicy != nil || bytes.Contains(canonical(base.Source), []byte("execution_policy")) {
		t.Fatal("legacy genesis was changed or implicitly upgraded")
	}
	var decoded DagSource
	if decodeStrict(canonical(base.Source), &decoded) != nil || !bytes.Equal(canonical(decoded), canonical(base.Source)) || validateDagSource(decoded) != nil {
		t.Fatal("legacy canonical source no longer roundtrips")
	}
}

func TestDagExecutionPolicyRejectsEveryChangedRuleAfterRehashedGenesis(t *testing.T) {
	source := boundPolicySource(t)
	if validateDagSource(source) != nil {
		t.Fatal("exact current policy rejected")
	}
	for i := 0; i < reflect.TypeOf(DagExecutionPolicy{}).NumField(); i++ {
		t.Run(reflect.TypeOf(DagExecutionPolicy{}).Field(i).Name, func(t *testing.T) {
			changed := source
			policy := *source.Genesis.ExecutionPolicy
			field := reflect.ValueOf(&policy).Elem().Field(i)
			switch field.Kind() {
			case reflect.Int:
				field.SetInt(field.Int() + 1)
			case reflect.Uint64:
				field.SetUint(field.Uint() + 1)
			case reflect.String:
				field.SetString(field.String() + "-other")
			default:
				t.Fatal("unreviewed policy field type")
			}
			changed.Genesis.ExecutionPolicy = &policy
			changed.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", changed.Genesis)
			if validateDagSource(changed) == nil {
				t.Fatal("unknown self-declared policy accepted")
			}
		})
	}
}

func TestDagExecutionPolicyRejectsLegacyInjectionMissingAndUnknownVersions(t *testing.T) {
	base, _ := dagFixture(t)
	policy := currentDagExecutionPolicy()
	for _, mode := range []string{"legacy_injection", "missing_policy", "unknown_genesis", "unknown_profile"} {
		t.Run(mode, func(t *testing.T) {
			changed := boundPolicySource(t)
			switch mode {
			case "legacy_injection":
				changed = base.Source
				changed.Genesis.ExecutionPolicy = &policy
			case "missing_policy":
				changed.Genesis.ExecutionPolicy = nil
			case "unknown_genesis":
				changed.Genesis.Schema = "gg.parallel-dag.genesis.v999"
			case "unknown_profile":
				copy := *changed.Genesis.ExecutionPolicy
				copy.Profile = "other"
				changed.Genesis.ExecutionPolicy = &copy
			}
			changed.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", changed.Genesis)
			if validateDagSource(changed) == nil {
				t.Fatal("policy downgrade/injection accepted")
			}
		})
	}
}

func TestDagExecutionPolicyOwnsCallerDescriptorAndExecutesActualSignatures(t *testing.T) {
	legacy, keys := dagFixture(t)
	source := boundPolicySource(t)
	execution, err := newDagExecution(source, legacy.Anchor)
	if err != nil {
		t.Fatal(err)
	}
	before := canonical(execution.Source)
	if execution.Source.GenesisHash == legacy.Source.GenesisHash || execution.Manifest.SourceHash == legacy.Manifest.SourceHash {
		t.Fatal("genesis policy was not bound to immutable source and manifest")
	}
	source.Genesis.ExecutionPolicy.HistoryRaw++
	if !bytes.Equal(before, canonical(execution.Source)) || validateDagSource(execution.Source) != nil {
		t.Fatal("caller mutation changed owned execution policy")
	}
	batch := dagBatchWire(t, execution, dagWire(t, execution, keys, 0, 3))
	next, err := applyDagBatch(execution, batch, 1700000002000000000)
	if err != nil || next.Commitment.Transactions != 3 || next.nonces[0] != 3 || execution.nonces[0] != 0 {
		t.Fatal("bound policy changed real signature/nonce execution", err)
	}
}

func TestDagExecutionPolicyJSONPresenceRejectsNullLegacyInjectionAndNewOmission(t *testing.T) {
	legacy, _ := dagFixture(t)
	for _, mode := range []string{"legacy_null", "legacy_descriptor", "new_null", "new_missing"} {
		t.Run(mode, func(t *testing.T) {
			source := legacy.Source
			if mode == "new_null" || mode == "new_missing" {
				source = boundPolicySource(t)
			}
			var fields map[string]json.RawMessage
			if err := json.Unmarshal(canonical(source.Genesis), &fields); err != nil {
				t.Fatal(err)
			}
			switch mode {
			case "legacy_null", "new_null":
				fields["execution_policy"] = json.RawMessage("null")
			case "legacy_descriptor":
				fields["execution_policy"] = canonical(currentDagExecutionPolicy())
			case "new_missing":
				delete(fields, "execution_policy")
			}
			raw, err := json.Marshal(fields)
			if err != nil {
				t.Fatal(err)
			}
			var decoded DagGenesis
			if decodeStrict(raw, &decoded) == nil {
				t.Fatal("JSON policy presence silently changed protocol interpretation")
			}
		})
	}
}

func TestDagExecutionPolicyKeepsExactHistoryAdmissionBoundary(t *testing.T) {
	_, keys := dagFixture(t)
	for _, bound := range []bool{false, true} {
		name := "legacy"
		if bound {
			name = "bound"
		}
		t.Run(name, func(t *testing.T) {
			base, _ := dagFixture(t)
			if bound {
				var err error
				base, err = newDagExecution(boundPolicySource(t), base.Anchor)
				if err != nil {
					t.Fatal(err)
				}
			}
			wire := dagWire(t, base, keys, 0, 3)
			record, err := decodeDagBlock(wire, base.Source, 1700000002000000000)
			if err != nil {
				t.Fatal(err)
			}
			at := base.clone()
			at.bytes = DagMaxHistoryWire - len(wire)
			if err = at.admit(record); err != nil || at.bytes != DagMaxHistoryWire || at.Commitment.Transactions != 0 || at.nonces[0] != 3 {
				t.Fatal("exact original byte boundary was not retained", err)
			}
			over := base.clone()
			over.bytes = DagMaxHistoryWire - len(wire) + 1
			if err = over.admit(record); err == nil || err.Error() != "GG_DAG_EXECUTION_LIMIT" || over.nonces[0] != 0 || over.orderCount() != 0 {
				t.Fatal("over-boundary admission changed original rules or nonce")
			}
		})
	}
}
