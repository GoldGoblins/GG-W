pragma Singleton
import QtQuick

QtObject {
    id: root
    property var backend: null
    property var hostOverlay: null
    readonly property int revision: backend ? backend.revision : 0
    property var popup: null
    property var selectionOwner: null
    property bool applicationVisible: true
    property real nowMillis: Date.now()
    property Timer deadlineTimer: Timer {
        interval:1000;repeat:true
        running:root.applicationVisible && root.backend && root.backend.latestDeadlineTime>root.nowMillis
        onTriggered:root.nowMillis=Date.now()
    }
    property Connections deadlineConnections: Connections {
        target:root.backend
        function onStylesChanged(){if(root.backend.latestDeadlineTime>0)root.nowMillis=Date.now()}
    }
    onApplicationVisibleChanged:if(applicationVisible)nowMillis=Date.now()
    onBackendChanged:nowMillis=Date.now()
    // Keep menu creation outside normal text loading. Popup uses GgButton and
    // GGText; none of that menu tree is needed before a user opens it.
    property var popupFactory: null
    function colorFor(key, fallback) {
        var dependency=revision
        if(backend && key && backend.scaleFor(key,"solid")==="deadline")return backend.deadlineColor(key,String(fallback),nowMillis)
        return backend && key ? backend.colorFor(key,String(fallback)) : fallback
    }
    function styleFor(key,text) {
        var dependency=revision
        if(!backend || !key)return {color:"",scale:"solid",ranges:[]}
        try{return JSON.parse(backend.styleFor(key,String(text)))}catch(error){return {color:"",scale:"solid",ranges:[]}}
    }
    function hasColor(key) {var style=styleFor(key,"");return !!style.color || style.scale!=="solid"}
    function scaleFor(key,fallback) {var dependency=revision;return backend && key ? backend.scaleFor(key,fallback || "solid") : fallback || "solid"}
    function colorForValue(key,fallback,fraction) {var dependency=revision;if(backend && key && backend.scaleFor(key,"solid")==="deadline")return backend.deadlineColor(key,String(fallback),nowMillis);return backend && key ? backend.colorForValue(key,String(fallback),fraction) : fallback}
    function hasRanges(key,text) {return styleFor(key,text).ranges.length>0}
    function hasRangeStyle(key) {
        var dependency=revision
        if(!backend || !key)return false
        return typeof backend.hasRangeStyle==="function"?backend.hasRangeStyle(key):true
    }
    function formatted(key,text) {
        var dependency=revision
        return backend && key ? backend.richText(key,String(text)) : escapeText(String(text))
    }
    function escapeText(text) {
        var output=""
        for(var index=0;index<text.length;index++) {
            var ch=text.charAt(index)
            if(ch===" ") {
                var end=index+1;while(end<text.length && text.charAt(end)===" ")end++
                var interior=index>0 && end<text.length && !/[\r\n]/.test(text.charAt(index-1)) && !/[\r\n]/.test(text.charAt(end))
                for(var at=index;at<end;at++)output+=interior && at===end-1?" ":"&nbsp;"
                index=end-1
            } else output+=ch==="&"?"&amp;":ch==="<"?"&lt;":ch===">"?"&gt;":ch==='"'?"&quot;":ch==="\n"?"<br/>":ch
        }
        return output
    }
    function wordRange(text,position) {
        if(!backend)return [-1,-1]
        try{return JSON.parse(backend.wordRange(String(text),Math.floor(position)))}catch(error){return [-1,-1]}
    }
    function blocked(item) {
        var node=item
        for(var depth=0;node && depth<48;depth++,node=node.parent) {
            if(typeof node.colorCustomizationEnabled==="boolean" && !node.colorCustomizationEnabled)return true
            if(typeof node.colorCustomizationExcluded==="boolean" && node.colorCustomizationExcluded)return true
            if(typeof node.sensitiveUi==="boolean" && node.sensitiveUi)return true
            var name=String(node.objectName || "").toLowerCase()
            if(/walletcreationwizard|walletrecoverypanel|mnemonic|password|privatekey|chatmessagebody|chatinput|ggcolorpopup/.test(name))return true
            if(typeof node.echoMode==="number" && node.echoMode!==0)return true
        }
        return false
    }
    function permittedFor(item) {return !!item && !blocked(item)}
    function keyFor(item,semanticHint) {
        if(!item || blocked(item))return ""
        if(typeof semanticHint==="string" && semanticHint.length>0)return semanticHint
        var scoped=item
        for(var scopeDepth=0;scoped && scopeDepth<32;scopeDepth++,scoped=scoped.parent)if(typeof scoped.uiColorScope==="string" && scoped.uiColorScope.length>0)return scoped.uiColorScope
        var pieces=[],node=item
        for(var depth=0;node && depth<32;depth++,node=node.parent) {
            var type=String(node).split("(")[0].replace(/_QML(?:TYPE)?_[0-9]+/g,"")
            pieces.push(type+":"+String(node.objectName || ""))
        }
        // Hash only object metadata. Displayed text, addresses and selected
        // characters never become persistence keys or filesystem paths.
        var raw=pieces.join("/"), hash=2166136261
        for(var index=0;index<raw.length;index++)hash=Math.imul(hash^raw.charCodeAt(index),16777619)>>>0
        return "ui.item."+hash.toString(16)
    }
    function openFor(target,key,text,start,end,sceneX,sceneY,selected,fallback) {
        if(!backend || !hostOverlay || !target || blocked(target) || !key)return false
        if(!popupFactory)popupFactory=Qt.createComponent(Qt.resolvedUrl("GGColorPopup.qml"))
        if(popupFactory.status!==Component.Ready)return false
        if(!popup)popup=popupFactory.createObject(hostOverlay,{parent:hostOverlay})
        if(!popup)return false
        popup.selectionTarget=target
        popup.openTarget(key,String(text),start,end,typeof fallback==="undefined" ? String(target.color || "#d8dee9") : String(fallback),!!selected,Number(sceneX),Number(sceneY))
        return true
    }
    function openWhole(target,key,fallback,x,y) {return openFor(target,key,"",-1,-1,x,y,false,fallback)}
    function choose(key,text,start,end,color,whole) {
        if(!backend)return false
        return whole || start<0 || end<=start ? backend.setColor(key,color) : backend.setRangeColor(key,text,start,end,color)
    }
    function reset(key) {return backend ? backend.reset(key) : false}
    function setScale(key,mode) {return backend ? backend.setScale(key,mode) : false}
    function setDeadline(key,start,end) {return backend ? backend.setDeadline(key,start,end) : false}
}
