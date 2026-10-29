import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

import "MarketFormat.js" as Format

// The popup is a companion view. Its controls share the existing wallet model
// and actions; it never creates balances, quotes or a second transaction flow.
Column {
    id: root
    required property Item walletPanel
    spacing: 2
    component Caption: GGText {
        font.family: "monospace"; font.pixelSize: 10
        color: RuntimeTheme.GGTheme.muted; textFormat: Text.PlainText; elide: Text.ElideRight
    }
    component Action: CryptoButton {
        implicitHeight: 26; height: 26; font.pixelSize: 10
        leftPadding: 5; rightPadding: 5; topPadding: 2; bottomPadding: 2
        enabled: !root.walletPanel.busy && !root.walletPanel.approvalPending
    }
    Item {
        width: parent.width; height: 78
        WalletAllocationArc { property string uiColorScope: "ui.widget.WalletCompactHeader.WalletAllocationArc.1";
            anchors.horizontalCenter: parent.horizontalCenter
            width: 148; height: 64; y: 0
            segments: root.walletPanel.allocation.segments
            description: root.walletPanel.allocation.description+"\n"
                +(root.walletPanel.summary.account_count || root.walletPanel.scopedAccounts.length)+" konton · "
                +(root.walletPanel.summary.network_count || 0)+" nätverk · "+root.walletPanel.readStatus
        }
        Column {
            width: parent.width; y: 35; spacing: 1
            Caption { colorKey: "ui.WalletCompactHeader.1";
                objectName: "walletTotalValue"; width: parent.width
                text: root.walletPanel.showLab ? "GG-LAB"
                    : root.walletPanel.summary.known_value_usd === null || root.walletPanel.summary.known_value_usd === undefined
                    ? "—" : Format.exactMoney(root.walletPanel.summary.known_value_usd)
                color: RuntimeTheme.GGTheme.bright; font.pixelSize: 26; font.bold: true
                horizontalAlignment: Text.AlignHCenter
                fontSizeMode: Text.HorizontalFit; minimumPixelSize: 18
            }
            Caption { colorKey: "ui.WalletCompactHeader.2";
                width:parent.width;horizontalAlignment:Text.AlignHCenter;font.pixelSize:9
                text:root.walletPanel.showLab ? "Separata sessionstillgångar"
                    : root.walletPanel.allocation.unpricedCount ? "Värderad del · "+root.walletPanel.allocation.unpricedCount+" ej prissatta"
                    : root.walletPanel.allocation.valuedCount ? root.walletPanel.allocation.description.split("\n").slice(1,3).join(" · ") : "Värderad del"
            }
        }
        Row {
            anchors.right: parent.right; y: 2; spacing: 4
            Action { property string uiColorScope: "ui.control.WalletCompactHeader.1";
                objectName: "walletRefreshOverview"; width: 26; implicitWidth: 26
                Accessible.name: "Uppdatera valda kontons saldon och priser"
                text: "↻"; font.pixelSize: 15
                enabled: !root.walletPanel.busy && !root.walletPanel.approvalPending && root.walletPanel.scopedAccounts.length > 0 && !root.walletPanel.showLab
                tip: root.walletPanel.readStatus + " · läs saldon och priser för valda konton"
                onClicked: root.walletPanel.refreshOverview()
            }
            Action { property string uiColorScope: "ui.control.WalletCompactHeader.2";
                objectName: "walletOverviewExpand"; width: 26; implicitWidth: 26
                Accessible.name: "Öppna kontoöversikten i CRYPTO"
                text: "↗"; font.pixelSize: 15; enabled: true
                tip: "Öppna kontoöversikten i CRYPTO"
                onClicked: root.walletPanel.workspaceRequested()
            }
        }
    }
    Row {
        width: parent.width; spacing: 4
        CryptoPick { property string uiColorScope: "ui.control.WalletCompactHeader.3";
            objectName: "walletAccountFilter"; width: parent.width - 30; height: 26
            visible: !root.walletPanel.showLab
            enabled: !root.walletPanel.noAccounts && !root.walletPanel.approvalPending
            font.pixelSize: 10; leftPadding: 6; rightPadding: 22; topPadding: 2; bottomPadding: 2
            model: root.walletPanel.accountFilterChoices
            textRole: "name"
            currentIndex: root.walletPanel.accountScopeIndex()
            onActivated: root.walletPanel.selectAccountScope(model[currentIndex])
        }
        Action { property string uiColorScope: "ui.control.WalletCompactHeader.4";
            objectName: "walletPublicHoldings"; width: parent.width - 30; visible: root.walletPanel.showLab
            text: "← Publika innehav"; onClicked: root.walletPanel.showLab = false
        }
        Action { property string uiColorScope: "ui.control.WalletCompactHeader.5";
            objectName: "walletAddAccount"; width: 26; implicitWidth: 26
            Accessible.name: "Lägg till eller skapa wallet"
            text: "+"; font.pixelSize: 14; tip: "Bevaka, skapa eller återställ wallet"
            onClicked: root.walletPanel.openAccountMenu()
        }
    }
    Row {
        width: parent.width; spacing: 6; visible: !root.walletPanel.showLab
        Action { property string uiColorScope: "ui.control.WalletCompactHeader.6";
            objectName: "walletReceive"; width: (parent.width - 6) / 2; text: "↓ Ta emot"
            enabled: !root.walletPanel.busy && !root.walletPanel.approvalPending && !root.walletPanel.noAccounts
            onClicked: root.walletPanel.openActions("receive")
        }
        Action { property string uiColorScope: "ui.control.WalletCompactHeader.7";
            objectName: "walletSend"; width: (parent.width - 6) / 2
            text: root.walletPanel.selectedAccountRole==="TRADING" ? "↗ Till förvaring" : root.walletPanel.selectedAccountRole==="STORAGE" ? "↗ Till trading" : "↗ Skicka"
            enabled: !root.walletPanel.busy && !root.walletPanel.approvalPending && !root.walletPanel.noAccounts
            tip: "Välj konto och tillgång. Sändning kräver en stödd GG-wallet och granskning."
            onClicked: root.walletPanel.selectedAccountRole ? root.walletPanel.openRoleMove(root.walletPanel.selectedAccountRole==="TRADING" ? "STORAGE" : "TRADING") : root.walletPanel.openActions("send")
        }
    }
    Caption { colorKey: "ui.WalletCompactHeader.3";
        visible:false
        width: parent.width; font.pixelSize: 9
        text: root.walletPanel.showLab ? "GG-labb · lokala sessionstillgångar"
            : (root.walletPanel.summary.account_count || root.walletPanel.scopedAccounts.length) + " konton · "
                + (root.walletPanel.summary.network_count || 0) + " nätverk · "
                + (root.walletPanel.summary.unpriced_count || 0) + " ej prissatta"
        ToolTip.visible: metadataHover.containsMouse
        ToolTip.text: text + "\n" + root.walletPanel.readStatus
        MouseArea {id: metadataHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton}
    }
    Row {
        width: parent.width; spacing: 6; visible: !root.walletPanel.showLab
        CryptoField { property string uiColorScope: "ui.widget.WalletCompactHeader.CryptoField.9";
            objectName: "walletAssetSearch"; width: Math.max(80,parent.width - network.width - 6); height: 26
            font.pixelSize: 10; leftPadding: 6; rightPadding: 4; topPadding: 2; bottomPadding: 2
            placeholderText: "⌕ Sök tillgång…"; Accessible.name: "Sök bland dina tillgångar"
            onTextChanged: root.walletPanel.query = text
            background: Rectangle {color: "transparent"; border.color: RuntimeTheme.GGTheme.line}
        }
        CryptoPick { property string uiColorScope: "ui.control.WalletCompactHeader.8";
            id: network; objectName: "walletNetworkFilter"; width: 106; height: 26
            font.pixelSize: 10; leftPadding: 6; rightPadding: 20; topPadding: 2; bottomPadding: 2
            enabled: !root.walletPanel.approvalPending
            model: [{id:"",name:"Alla nätverk"}].concat(root.walletPanel.publicNetworks.map(function(n){return {id:n.id,name:n.name}}))
            textRole: "name"
            currentIndex: {for(var i=0;i<model.length;i++)if(model[i].id===root.walletPanel.chain)return i;return 0}
            onActivated: root.walletPanel.chain = model[currentIndex].id
        }
    }
    Rectangle {width: parent.width; height: 1; color: RuntimeTheme.GGTheme.line}
    Caption { colorKey: "ui.WalletCompactHeader.4";
        width: parent.width; visible: root.walletPanel.wallet.truncated === true
        text: "Visar " + root.walletPanel.wallet.displayed_positions + " av " + root.walletPanel.wallet.position_count + " · delsumma"
        color: RuntimeTheme.GGTheme.accent; wrapMode: Text.WordWrap; elide: Text.ElideNone
    }
}
