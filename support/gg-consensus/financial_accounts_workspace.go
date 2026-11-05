package main

// Private block-local COW topology. No intermediate hash/link is published.
// Base references are immutable, fully bound by the existing loader. Every
// published node is constructed by the unchanged immutable tree.make.
import (
	"context"
	"errors"
	"runtime"
	"strconv"
	"sync"
	"sync/atomic"
	"unsafe"
)

const financialAccountWorkspaceBytes uint64 = 32 << 20
const financialAccountWorkspaceReserve uint64 = 4 << 20

var errFinancialAccountWorkspaceBudget = errors.New("GG_PRIVATE_ACCOUNT_WORKSPACE_BUDGET")

type financialAccountWorkspaceRef struct {
	base  financialAccountRef
	owned *financialAccountWorkspaceNode
}

type financialAccountWorkspaceNode struct {
	owner        *financialAccountWorkspace
	account      Account
	left, right  financialAccountWorkspaceRef
	count, total uint64
	height       int
}

type financialAccountWorkspace struct {
	base         financialAccountTree
	root         financialAccountWorkspaceRef
	bytes, limit uint64
	nodes        int
}

// This charge includes the mutable node, the immutable result's public and
// checked value copies/refs, two maximum encoded buffers, and fixed allocator/
// string slack. The separate reserve covers bounded stack/encoder temporaries.
// It is a private admission estimate, not an OS RSS guarantee. Kernel limits
// remain unchanged and budget fallback adds no transaction rejection.
func financialAccountWorkspaceNodeCharge() uint64 {
	return uint64(unsafe.Sizeof(financialAccountWorkspaceNode{})) +
		2*uint64(unsafe.Sizeof(financialAccountNode{})) +
		uint64(unsafe.Sizeof(checkedFinancialAccountNode{})) +
		3*uint64(unsafe.Sizeof(financialAccountRef{})) +
		2*financialAccountNodeMaxBytes + 256
}

func newFinancialAccountWorkspace(tree financialAccountTree, limit uint64) (*financialAccountWorkspace, error) {
	if !tree.rulesBound() || !validFinancialAccountLink(tree.root.link, tree.rules, tree.rulesHash) {
		return nil, errFinancialAccount
	}
	if limit < financialAccountWorkspaceReserve || limit > financialAccountWorkspaceBytes {
		return nil, errFinancialAccountWorkspaceBudget
	}
	return &financialAccountWorkspace{base: tree, root: financialAccountWorkspaceRef{base: tree.root},
		bytes: financialAccountWorkspaceReserve, limit: limit}, nil
}

func (work *financialAccountWorkspace) allocate(account Account, left, right financialAccountWorkspaceRef) (*financialAccountWorkspaceNode, error) {
	charge := financialAccountWorkspaceNodeCharge()
	if work.nodes >= financialAccountStageMaxNodes || charge > work.limit-work.bytes {
		return nil, errFinancialAccountWorkspaceBudget
	}
	work.nodes++
	work.bytes += charge
	return &financialAccountWorkspaceNode{owner: work, account: account, left: left, right: right}, nil
}

func (work *financialAccountWorkspace) meta(ref financialAccountWorkspaceRef) (uint64, int, uint64, error) {
	if ref.owned != nil {
		node := ref.owned
		if node.owner != work || node.count == 0 || node.count > work.base.rules.MaxAccounts ||
			node.height < 1 || node.height > financialAccountPathMax || node.total > work.base.rules.MaxTotal {
			return 0, 0, 0, errFinancialAccount
		}
		return node.count, node.height, node.total, nil
	}
	if !validFinancialAccountLink(ref.base.link, work.base.rules, work.base.rulesHash) {
		return 0, 0, 0, errFinancialAccount
	}
	total, ok := financialAccountAmount(ref.base.link.Total, work.base.rules.MaxTotal)
	if !ok {
		return 0, 0, 0, errFinancialAccount
	}
	return ref.base.link.Count, ref.base.link.Height, total, nil
}

func (work *financialAccountWorkspace) mutable(ctx context.Context, ref *financialAccountWorkspaceRef, lower, upper string) (*financialAccountWorkspaceNode, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if !work.base.rulesBound() {
		return nil, errFinancialAccount
	}
	if ref.owned != nil {
		node := ref.owned
		if _, _, _, err := work.meta(*ref); err != nil {
			return nil, err
		}
		if lower != "" && node.account.Address <= lower || upper != "" && node.account.Address >= upper {
			return nil, errFinancialAccount
		}
		return node, nil
	}
	node, left, right, err := work.base.load(ctx, ref.base, lower, upper)
	if err != nil || node == nil {
		return nil, err
	}
	total, ok := financialAccountAmount(node.Total, work.base.rules.MaxTotal)
	if !ok {
		return nil, errFinancialAccount
	}
	owned, err := work.allocate(node.Account.account(), financialAccountWorkspaceRef{base: left}, financialAccountWorkspaceRef{base: right})
	if err != nil {
		return nil, err
	}
	owned.count, owned.height, owned.total = node.Count, node.Height, total
	ref.owned = owned
	return owned, nil
}

func (work *financialAccountWorkspace) recompute(node *financialAccountWorkspaceNode) error {
	if node == nil || node.owner != work || !financialAccountAddress(node.account.Address) {
		return errFinancialAccount
	}
	balance, ok := financialAccountAmount(node.account.Balance, work.base.rules.MaxTotal)
	lc, lh, lt, err := work.meta(node.left)
	if err != nil {
		return err
	}
	rc, rh, rt, err := work.meta(node.right)
	if err != nil {
		return err
	}
	if !ok || lt > work.base.rules.MaxTotal-balance || rt > work.base.rules.MaxTotal-balance-lt ||
		lc >= work.base.rules.MaxAccounts || rc > work.base.rules.MaxAccounts-1-lc || lh-rh > 1 || rh-lh > 1 {
		return errFinancialAccount
	}
	height := lh
	if rh > height {
		height = rh
	}
	if height >= financialAccountPathMax {
		return errFinancialAccount
	}
	node.count, node.height, node.total = lc+rc+1, height+1, lt+balance+rt
	return nil
}

func (work *financialAccountWorkspace) balance(ctx context.Context, node *financialAccountWorkspaceNode) (financialAccountWorkspaceRef, error) {
	if err := ctx.Err(); err != nil {
		return financialAccountWorkspaceRef{}, err
	}
	_, lh, _, err := work.meta(node.left)
	if err != nil {
		return financialAccountWorkspaceRef{}, err
	}
	_, rh, _, err := work.meta(node.right)
	if err != nil {
		return financialAccountWorkspaceRef{}, err
	}
	own := func(value *financialAccountWorkspaceNode) financialAccountWorkspaceRef {
		return financialAccountWorkspaceRef{owned: value}
	}
	switch {
	case lh-rh > 1:
		if lh-rh != 2 {
			return financialAccountWorkspaceRef{}, errFinancialAccount
		}
		child, err := work.mutable(ctx, &node.left, "", node.account.Address)
		if err != nil || child == nil {
			if err == nil {
				err = errFinancialAccount
			}
			return financialAccountWorkspaceRef{}, err
		}
		_, ah, _, err := work.meta(child.left)
		if err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		_, bh, _, err := work.meta(child.right)
		if err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		if ah >= bh {
			node.left = child.right
			if err = work.recompute(node); err != nil {
				return financialAccountWorkspaceRef{}, err
			}
			child.right = own(node)
			if err = work.recompute(child); err != nil {
				return financialAccountWorkspaceRef{}, err
			}
			return own(child), nil
		}
		middle, err := work.mutable(ctx, &child.right, child.account.Address, node.account.Address)
		if err != nil || middle == nil {
			if err == nil {
				err = errFinancialAccount
			}
			return financialAccountWorkspaceRef{}, err
		}
		child.right, node.left = middle.left, middle.right
		if err = work.recompute(child); err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		if err = work.recompute(node); err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		middle.left, middle.right = own(child), own(node)
		if err = work.recompute(middle); err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		return own(middle), nil
	case rh-lh > 1:
		if rh-lh != 2 {
			return financialAccountWorkspaceRef{}, errFinancialAccount
		}
		child, err := work.mutable(ctx, &node.right, node.account.Address, "")
		if err != nil || child == nil {
			if err == nil {
				err = errFinancialAccount
			}
			return financialAccountWorkspaceRef{}, err
		}
		_, ah, _, err := work.meta(child.left)
		if err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		_, bh, _, err := work.meta(child.right)
		if err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		if bh >= ah {
			node.right = child.left
			if err = work.recompute(node); err != nil {
				return financialAccountWorkspaceRef{}, err
			}
			child.left = own(node)
			if err = work.recompute(child); err != nil {
				return financialAccountWorkspaceRef{}, err
			}
			return own(child), nil
		}
		middle, err := work.mutable(ctx, &child.left, node.account.Address, child.account.Address)
		if err != nil || middle == nil {
			if err == nil {
				err = errFinancialAccount
			}
			return financialAccountWorkspaceRef{}, err
		}
		node.right, child.left = middle.left, middle.right
		if err = work.recompute(node); err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		if err = work.recompute(child); err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		middle.left, middle.right = own(node), own(child)
		if err = work.recompute(middle); err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		return own(middle), nil
	default:
		if err = work.recompute(node); err != nil {
			return financialAccountWorkspaceRef{}, err
		}
		return own(node), nil
	}
}

func (work *financialAccountWorkspace) put(ctx context.Context, ref financialAccountWorkspaceRef, account Account, depth int, lower, upper string) (financialAccountWorkspaceRef, error) {
	if depth >= financialAccountPathMax {
		return financialAccountWorkspaceRef{}, errFinancialAccount
	}
	node, err := work.mutable(ctx, &ref, lower, upper)
	if err != nil {
		return financialAccountWorkspaceRef{}, err
	}
	if node == nil {
		empty := financialAccountWorkspaceRef{base: financialAccountRef{link: financialAccountEmpty(work.base.rulesHash)}}
		node, err = work.allocate(account, empty, empty)
		if err != nil {
			return financialAccountWorkspaceRef{}, err
		}
	} else if account.Address < node.account.Address {
		node.left, err = work.put(ctx, node.left, account, depth+1, lower, node.account.Address)
	} else if account.Address > node.account.Address {
		node.right, err = work.put(ctx, node.right, account, depth+1, node.account.Address, upper)
	} else {
		node.account = account
	}
	if err != nil {
		return financialAccountWorkspaceRef{}, err
	}
	return work.balance(ctx, node)
}

func (work *financialAccountWorkspace) set(ctx context.Context, account Account) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if !financialAccountAddress(account.Address) {
		return errFinancialAccount
	}
	if _, ok := financialAccountAmount(account.Balance, work.base.rules.MaxTotal); !ok {
		return errFinancialAccount
	}
	ref, err := work.put(ctx, work.root, account, 0, "", "")
	if err != nil {
		return err
	}
	work.root = ref
	return ctx.Err()
}

func (work *financialAccountWorkspace) freeze(ctx context.Context) (financialAccountTree, error) {
	var visited atomic.Int64
	workers := dagTxSignatureWorkers(work.nodes, runtime.GOMAXPROCS(0))
	slots := make(chan struct{}, workers-1)
	var visit func(financialAccountWorkspaceRef, string, string, int) (financialAccountRef, error)
	visit = func(ref financialAccountWorkspaceRef, lower, upper string, depth int) (financialAccountRef, error) {
		if err := ctx.Err(); err != nil {
			return financialAccountRef{}, err
		}
		if depth > financialAccountPathMax || !work.base.rulesBound() {
			return financialAccountRef{}, errFinancialAccount
		}
		if ref.owned == nil {
			if _, _, _, err := work.meta(ref); err != nil {
				return financialAccountRef{}, err
			}
			return ref.base, nil
		}
		count := visited.Add(1)
		if count > int64(work.nodes) || count > financialAccountStageMaxNodes {
			return financialAccountRef{}, errFinancialAccount
		}
		node := ref.owned
		if node.owner != work || lower != "" && node.account.Address <= lower || upper != "" && node.account.Address >= upper {
			return financialAccountRef{}, errFinancialAccount
		}
		var left, right financialAccountRef
		var leftErr, rightErr error
		var joined sync.WaitGroup
		parallel := false
		if node.count >= 256 && node.left.owned != nil && node.right.owned != nil {
			select {
			case slots <- struct{}{}:
				parallel = true
				joined.Add(1)
				go func() {
					defer joined.Done()
					defer func() { <-slots }()
					left, leftErr = visit(node.left, lower, node.account.Address, depth+1)
				}()
			default:
			}
		}
		if !parallel {
			left, leftErr = visit(node.left, lower, node.account.Address, depth+1)
			if leftErr != nil {
				return financialAccountRef{}, leftErr
			}
		}
		right, rightErr = visit(node.right, node.account.Address, upper, depth+1)
		joined.Wait()
		if leftErr != nil {
			return financialAccountRef{}, leftErr
		}
		if rightErr != nil {
			return financialAccountRef{}, rightErr
		}
		result, err := work.base.make(node.account, left, right)
		if err != nil {
			return financialAccountRef{}, err
		}
		total, ok := financialAccountAmount(result.link.Total, work.base.rules.MaxTotal)
		if !ok || result.link.Count != node.count || result.link.Height != node.height || total != node.total {
			return financialAccountRef{}, errFinancialAccount
		}
		if err = ctx.Err(); err != nil {
			return financialAccountRef{}, err
		}
		return result, nil
	}
	root, err := visit(work.root, "", "", 0)
	if err != nil {
		return work.base, err
	}
	if err = ctx.Err(); err != nil {
		return work.base, err
	}
	result := work.base
	result.root = root
	return result, nil
}

// The bound is deliberately conservative. A put has at most PathMax
// recursive frames. Each can clone one path base node plus at most two
// rotation base nodes (heavy child and middle). New accounts allocate at most
// once per final dirty address. Rotations move child references; they never
// duplicate a base position. COW therefore clones at most baseCount positions
// in total, and at most 3*PathMax positions for each update independently.
// This proof does not rely on the stronger one-rotation insertion property.
func financialAccountWorkspaceNodeBound(baseCount, dirtyCount, newDirtyCount uint64) (uint64, bool) {
	if dirtyCount > 2*financialMaxTransactions || newDirtyCount > dirtyCount || baseCount > 1<<32 {
		return 0, false
	}
	clones := dirtyCount * uint64(3*financialAccountPathMax)
	if clones > baseCount {
		clones = baseCount
	}
	return clones + newDirtyCount, true
}

// No COW object, lookup, clone, encoding or store operation occurs here.
// False is a private optimization miss, not a transaction rejection.
func (batch *protocolMoneyBatch) workspaceEligibility(ctx context.Context, addresses []string, limit uint64) (bool, uint64, error) {
	if err := ctx.Err(); err != nil {
		return false, 0, err
	}
	if !batch.tree.rulesBound() || !validFinancialAccountLink(batch.tree.root.link, batch.tree.rules, batch.tree.rulesHash) {
		return false, 0, errFinancialAccount
	}
	if len(addresses) > 2*financialMaxTransactions {
		return false, 0, nil
	}
	newDirty := uint64(0)
	for _, address := range addresses {
		if err := ctx.Err(); err != nil {
			return false, 0, err
		}
		row := batch.rows[address]
		if row == nil || !row.dirty {
			return false, 0, errFinancialAccount
		}
		if !row.wasPresent {
			newDirty++
		}
	}
	bound, ok := financialAccountWorkspaceNodeBound(batch.tree.root.link.Count, uint64(len(addresses)), newDirty)
	if !ok || bound > financialAccountStageMaxNodes || limit < financialAccountWorkspaceReserve || limit > financialAccountWorkspaceBytes {
		return false, bound, nil
	}
	charge := financialAccountWorkspaceNodeCharge()
	// Division avoids overflow and reserves exactly the same amount as the
	// construction-time allocation checks. No budget is raised.
	return charge > 0 && bound <= (limit-financialAccountWorkspaceReserve)/charge, bound, nil
}

func (batch *protocolMoneyBatch) finishWorkspace(ctx context.Context, addresses []string, limit uint64) (financialAccountTree, bool, error) {
	eligible, _, err := batch.workspaceEligibility(ctx, addresses, limit)
	if err != nil {
		return batch.tree, false, err
	}
	if !eligible {
		return batch.tree, false, nil
	}
	work, err := newFinancialAccountWorkspace(batch.tree, limit)
	if err == nil {
		for phase := 0; phase < 2 && err == nil; phase++ {
			for _, address := range addresses {
				if err = ctx.Err(); err != nil {
					break
				}
				row := batch.rows[address]
				debit := row.wasPresent && row.balance <= row.originalBalance
				if phase == 0 && !debit || phase == 1 && debit {
					continue
				}
				err = work.set(ctx, Account{Address: address, Balance: strconv.FormatUint(row.balance, 10), Nonce: row.nonce})
				if err != nil {
					break
				}
			}
		}
	}
	if err != nil {
		if cancelled := ctx.Err(); cancelled != nil {
			return batch.tree, false, cancelled
		}
		if errors.Is(err, errFinancialAccountWorkspaceBudget) {
			return batch.tree, false, nil
		}
		return batch.tree, false, err
	}
	result, err := work.freeze(ctx)
	if err != nil {
		return batch.tree, false, err
	}
	return result, true, nil
}
