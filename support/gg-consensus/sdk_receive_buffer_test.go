//go:build gg_sdk_receive_buffer_test

package conn

import (
	"bytes"
	"github.com/cometbft/cometbft/libs/log"
	tmp2p "github.com/cometbft/cometbft/proto/tendermint/p2p"
	"testing"
)

func TestGGCompletedMessageBufferBound(t *testing.T) {
	channel := &Channel{desc: ChannelDescriptor{RecvBufferCapacity: 4096, RecvMessageCapacity: 8 * 1024 * 1024}, Logger: log.NewNopLogger()}
	payload := bytes.Repeat([]byte{7}, 4*1024*1024)
	if result, err := channel.recvPacketMsg(tmp2p.PacketMsg{Data: payload[:2*1024*1024]}); err != nil || result != nil || len(channel.recving) != 2*1024*1024 {
		t.Fatal("incomplete changed")
	}
	result, err := channel.recvPacketMsg(tmp2p.PacketMsg{Data: payload[2*1024*1024:], EOF: true})
	if err != nil || !bytes.Equal(result, payload) || len(channel.recving) != 0 || cap(channel.recving) != 4096 {
		t.Fatal("large completed buffer retained or bytes changed")
	}
	small, err := channel.recvPacketMsg(tmp2p.PacketMsg{Data: []byte{9}, EOF: true})
	if err != nil || !bytes.Equal(small, []byte{9}) || cap(channel.recving) != 4096 || !bytes.Equal(result, payload) {
		t.Fatal("small reuse or previous delivered ownership changed")
	}
	ordinary := bytes.Repeat([]byte{3}, 64*1024+512)
	ordinaryResult, err := channel.recvPacketMsg(tmp2p.PacketMsg{Data: ordinary, EOF: true})
	if err != nil || !bytes.Equal(ordinaryResult, ordinary) || cap(channel.recving) < len(ordinary) || cap(channel.recving) > 256*1024 {
		t.Fatal("ordinary consensus part buffer was discarded")
	}
	retained := cap(channel.recving)
	ordinaryResult, err = channel.recvPacketMsg(tmp2p.PacketMsg{Data: ordinary, EOF: true})
	if err != nil || !bytes.Equal(ordinaryResult, ordinary) || cap(channel.recving) != retained {
		t.Fatal("ordinary part did not reuse its bounded buffer")
	}
	channel.desc.RecvMessageCapacity = 1
	if _, err = channel.recvPacketMsg(tmp2p.PacketMsg{Data: []byte{1, 2}, EOF: true}); err == nil || len(channel.recving) != 0 {
		t.Fatal("oversize no longer rejected")
	}
}
