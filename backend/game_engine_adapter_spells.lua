-- Local GG cast/stance controls. Retained stock addons keep their own cast bar.
if not GGSpellControls then
    local root=CreateFrame('Frame','GGSpellControls',UIParent)
    root:SetWidth(420);root:SetHeight(30);root:SetPoint('BOTTOM',UIParent,'BOTTOM',0,106)
    local buttons={}
    for i=1,4 do
        local b=CreateFrame('Button','GGSpellControl'..i,root)
        b:SetWidth(102);b:SetHeight(28);b:SetPoint('TOPLEFT',root,'TOPLEFT',(i-1)*106,0)
        local t=b:CreateTexture(nil,'BACKGROUND');t:SetAllPoints(b);t:SetTexture(.08,.18,.22,.94)
        local label=b:CreateFontString(nil,'OVERLAY');label:SetAllPoints(b);label:SetFont('',11);label:SetTextColor(.94,.87,.7,1)
        b.ggLabel=label;b.ggSlot=i+3
        b:SetScript('OnClick',function() CastSpell(this.ggSlot,'spell') end)
        buttons[i]=b
    end
    local cast=CreateFrame('Button','GGSpellCastBar',root)
    cast:SetWidth(310);cast:SetHeight(28);cast:SetPoint('BOTTOM',root,'TOP',0,6)
    local background=cast:CreateTexture(nil,'BACKGROUND');background:SetAllPoints(cast);background:SetTexture(.04,.09,.12,.95)
    local fill=cast:CreateTexture(nil,'ARTWORK');fill:SetPoint('TOPLEFT',cast,'TOPLEFT',0,0);fill:SetHeight(28);fill:SetTexture(.18,.52,.6,.9)
    local text=cast:CreateFontString(nil,'OVERLAY');text:SetAllPoints(cast);text:SetFont('',12);text:SetTextColor(1,.94,.78,1)
    cast:SetScript('OnClick',function() SpellStopCasting() end);cast:Hide()
    local breath=CreateFrame('Frame','GGBreathBar',root)
    breath:SetWidth(210);breath:SetHeight(20);breath:SetPoint('BOTTOM',cast,'TOP',0,5)
    local air=breath:CreateTexture(nil,'ARTWORK');air:SetPoint('TOPLEFT',breath,'TOPLEFT',0,0);air:SetHeight(20);air:SetTexture(.18,.47,.66,.94)
    local airText=breath:CreateFontString(nil,'OVERLAY');airText:SetAllPoints(breath);airText:SetFont('',11);airText:SetTextColor(1,1,1,1);breath:Hide()
    root:SetScript('OnUpdate',function()
        local s=GGSnapshot or {};local spells=s.client_controls and s.client_controls.spells
        if not spells then
            for i=1,4 do buttons[i]:Hide() end;cast:Hide();return
        end
        for i=1,4 do
            local b=buttons[i];local name=GetSpellName(b.ggSlot,'spell')
            if name then
                local start,duration=GetSpellCooldown(b.ggSlot,'spell')
                local left=duration and math.max(0,(start or 0)+duration-GetTime()) or 0
                b.ggLabel:SetText(name..(left>.05 and string.format(' %.1fs',left) or ''))
                b:SetAlpha(left>.05 and .5 or 1);b:Show()
            else b:Hide() end
        end
        local p=spells.pending
        if p then
            local left=math.max(0,p.remaining_s or 0);local duration=math.max(.01,p.duration or 1)
            fill:SetWidth(math.max(1,310*math.min(1,math.max(0,p.channel and left/duration or 1-left/duration))))
            text:SetText((p.name or '')..string.format(' · %.1fs · klicka för avbrott',left));cast:Show()
        else cast:Hide() end
        local survival=s.client_controls.survival
        if survival and survival.submerged then
            local left=math.max(0,survival.breath_s or 0)
            air:SetWidth(math.max(1,210*left/math.max(1,survival.max_breath_s or 60)))
            airText:SetText(string.format('Andning · %.1fs',left));breath:Show()
        else breath:Hide() end
    end)
end
