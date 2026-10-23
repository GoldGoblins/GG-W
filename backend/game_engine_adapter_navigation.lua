-- GG map artwork, with the original map catalog, selection and positioning API.
-- An installed addon may supply this original widget. The local GG addon set
-- does not require an installation's FrameXML, so bootstrap it when absent.
if not GameTooltip then
    local tip=CreateFrame("GameTooltip","GameTooltip",UIParent)
    tip:SetFrameStrata("TOOLTIP");tip:SetClampedToScreen(true);tip:Hide()
end
if not WorldMapFrame then
    local navButtons={}
    local function colorTexture(parent,r,g,b,a)
        local t=parent:CreateTexture(nil,"BACKGROUND")
        t:SetAllPoints(parent);t:SetTexture(r,g,b,a or 1);return t
    end
    local function label(parent,text,size)
        local f=parent:CreateFontString(nil,"OVERLAY")
        f:SetFont("",size or 13);f:SetTextColor(.94,.88,.72,1);f:SetText(text);return f
    end
    local function button(parent,name,text,x,y,action)
        local b=CreateFrame("Button",name,parent)
        b:SetWidth(76);b:SetHeight(25);b:SetPoint("TOPLEFT",parent,"TOPLEFT",x,y)
        colorTexture(b,.12,.22,.25,.98)
        local f=label(b,text);f:SetAllPoints(b)
        b:SetScript("OnClick",action)
        if parent==WorldMapFrame then table.insert(navButtons,b) end
        return b
    end
    local m=CreateFrame("Frame","WorldMapFrame",UIParent)
    m:SetFrameStrata("DIALOG");m:SetWidth(760);m:SetHeight(580);m:SetPoint("CENTER",UIParent,"CENTER",0,0)
    m:EnableMouse(true);colorTexture(m,.06,.10,.13,.98)
    local title=label(m,"GG · Världskarta",17);title:SetPoint("TOP",m,"TOP",0,-13)
    local detail=CreateFrame("Frame","WorldMapDetailFrame",m)
    detail:SetPoint("TOPLEFT",m,"TOPLEFT",14,-78);detail:SetWidth(732);detail:SetHeight(460)
    local map=CreateFrame("Button","WorldMapButton",detail);map:SetAllPoints(detail)
    local image=map:CreateTexture(nil,"ARTWORK");image:SetAllPoints(map)
    image:SetTexture("assets/authored/world/gg-first-planet-map.svg")
    local atlasTiles,overlayTiles,landmarkFrames={},{},{}
    local function atlasPiece(pool,index,texture,x,y,w,h,tw,th,layer)
        local t=pool[index]
        if not t then t=map:CreateTexture(nil,layer or "ARTWORK");pool[index]=t end
        -- Clip at the original 1002 x 668 detail bounds, preserving the
        -- final power-of-two texture piece's visible texel rectangle.
        w=math.min(w,1002-x);h=math.min(h,668-y)
        if w<=0 or h<=0 then t:Hide();return end
        t:ClearAllPoints();t:SetPoint("TOPLEFT",map,"TOPLEFT",x/1002*map:GetWidth(),-y/668*map:GetHeight())
        t:SetWidth(w/1002*map:GetWidth());t:SetHeight(h/668*map:GetHeight())
        t:SetTexture(texture);t:SetTexCoord(0,w/tw,0,h/th);t:Show()
    end
    local function originalArtwork(v)
        if not v.original then
            image:Show();for _,t in pairs(atlasTiles) do t:Hide() end
            for _,t in pairs(overlayTiles) do t:Hide() end;return
        end
        image:Hide()
        local prefix="Interface\\WorldMap\\"..(v.map_file or "World").."\\"..(v.map_file or "World")
        for i=1,12 do local col=math.mod(i-1,4);local row=math.floor((i-1)/4)
            atlasPiece(atlasTiles,i,prefix..i,col*256,row*256,256,256,256,256)
        end
        local used=0
        for i=1,math.min(GetNumMapOverlays(),128) do
            local texture,w,h,ox,oy=GetMapOverlayInfo(i)
            if texture and w>0 and h>0 then
                local cols=math.ceil(w/256);local rows=math.ceil(h/256)
                for r=0,rows-1 do for c=0,cols-1 do
                    if used<256 then
                        used=used+1;local pw=math.min(256,w-c*256);local ph=math.min(256,h-r*256)
                        local tw,th=16,16;while tw<pw do tw=tw*2 end;while th<ph do th=th*2 end
                        atlasPiece(overlayTiles,used,texture..(r*cols+c+1),ox+c*256,oy+r*256,pw,ph,tw,th,"OVERLAY")
                    end
                end end
            end
        end
        for i=used+1,table.getn(overlayTiles) do overlayTiles[i]:Hide() end
    end
    local player=colorTexture(CreateFrame("Frame","GGWorldMapPlayer",map),.35,1,.79,1)
    local playerFrame=GGWorldMapPlayer;playerFrame:SetWidth(8);playerFrame:SetHeight(8)
    local corpseFrame=CreateFrame("Frame","GGWorldMapCorpse",map);corpseFrame:SetWidth(8);corpseFrame:SetHeight(8)
    colorTexture(corpseFrame,.92,.92,.94,1)
    local marks={}
    for i=1,40 do
        local f=CreateFrame("Frame",nil,map);f:SetWidth(5);f:SetHeight(5)
        colorTexture(f,.56,.74,1,1);marks[i]=f
    end
    local coords=label(m,"",12);coords:SetPoint("BOTTOM",m,"BOTTOM",0,12)
    local function place(f,x,y)
        if x and y and x>=0 and x<=1 and y>=0 and y<=1 then
            f:ClearAllPoints();f:SetPoint("CENTER",map,"TOPLEFT",x*map:GetWidth(),-y*map:GetHeight());f:Show()
        else f:Hide() end
    end
    local function refresh()
        if not GG_GetMapView then return end
        local v=GG_GetMapView()
        title:SetText("GG · "..(v.name or "Världskarta"))
        image:SetTexCoord(v.u0 or 0,v.u1 or 1,v.v0 or 0,v.v1 or 1)
        originalArtwork(v)
        place(playerFrame,v.player_x,v.player_y);place(corpseFrame,v.corpse_x,v.corpse_y)
        for i=1,40 do local p=v.members and v.members[i];place(marks[i],p and p.x,p and p.y) end
        local count=math.min(GetNumMapLandmarks(),512)
        for i=1,count do
            local name,description,icon,x,y=GetMapLandmarkInfo(i)
            local f=landmarkFrames[i]
            if not f then f=CreateFrame("Frame",nil,map);f:SetWidth(5);f:SetHeight(5);colorTexture(f,.94,.76,.36,1);landmarkFrames[i]=f end
            place(f,x,y)
        end
        for i=count+1,table.getn(landmarkFrames) do landmarkFrames[i]:Hide() end
        coords:SetText(v.player_x and string.format("Du: %.1f%% / %.1f%% · %.0f × %.0f m",v.player_x*100,v.player_y*100,v.width or 0,v.height or 0) or "Spelaren finns på en annan karta")
        if v.original and v.continent==0 and table.getn({GetMapContinents()})==0 then
            title:SetText("GG · Kartdata saknas");coords:SetText("Den här världen saknar en kartkatalog")
        end
    end
    button(m,"GGMapWorld","Världen",14,-44,function() SetMapZoom(0);refresh() end)
    button(m,"GGMapHere","Här",94,-44,function() SetMapToCurrentZone();refresh() end)
    button(m,"GGMapContinentPrev","‹ Region",174,-44,function()
        local names={GetMapContinents()};if table.getn(names)>0 then SetMapZoom(math.max(1,GetCurrentMapContinent()-1),0);refresh() end
    end)
    button(m,"GGMapContinentNext","Region ›",254,-44,function()
        local names={GetMapContinents()};if table.getn(names)>0 then SetMapZoom(math.min(table.getn(names),GetCurrentMapContinent()+1),0);refresh() end
    end)
    button(m,"GGMapZonePrev","‹ Plats",334,-44,function()
        local c=GetCurrentMapContinent();if c>0 then SetMapZoom(c,math.max(0,GetCurrentMapZone()-1));refresh() end
    end)
    button(m,"GGMapZoneNext","Plats ›",414,-44,function()
        local c=GetCurrentMapContinent();local names={GetMapZones(c)};if c>0 then SetMapZoom(c,math.min(table.getn(names),GetCurrentMapZone()+1));refresh() end
    end)
    button(m,"GGMapClose","Stäng",670,-44,function() m:Hide() end)
    map:RegisterForClicks("LeftButtonUp","RightButtonUp")
    map:SetScript("OnClick",function()
        if arg1=="RightButton" then
            local c=GetCurrentMapContinent();if GetCurrentMapZone()>0 then SetMapZoom(c,0) else SetMapZoom(0) end
        else
            local x,y=GetCursorPosition()
            ProcessMapClick((x-map:GetLeft())/map:GetWidth(),(map:GetTop()-y)/map:GetHeight())
        end
        refresh()
    end)
    m:RegisterEvent("WORLD_MAP_UPDATE");m:RegisterEvent("SNAPSHOT")
    m:SetScript("OnEvent",refresh)
    m:SetScript("OnShow",function()
        m:SetWidth(math.max(320,math.min(760,UIParent:GetWidth()-32)))
        m:SetHeight(math.max(320,math.min(580,UIParent:GetHeight()-32)))
        local columns=math.max(3,math.min(7,math.floor((m:GetWidth()-28)/80)))
        local rows=math.ceil(table.getn(navButtons)/columns)
        for i,b in ipairs(navButtons) do
            b:ClearAllPoints();b:SetPoint("TOPLEFT",m,"TOPLEFT",14+math.mod(i-1,columns)*80,-44-math.floor((i-1)/columns)*29)
        end
        detail:ClearAllPoints();detail:SetPoint("TOPLEFT",m,"TOPLEFT",14,-52-rows*29)
        detail:SetWidth(m:GetWidth()-28);detail:SetHeight(m:GetHeight()-94-rows*29);refresh()
    end)
    function ToggleWorldMap() if m:IsShown() then m:Hide() else SetMapToCurrentZone();m:Show() end end
    m:Hide()
    local toggle=button(UIParent,"GGMapToggle","Karta · M",0,0,ToggleWorldMap)
    toggle:ClearAllPoints();toggle:SetPoint("TOPRIGHT",UIParent,"TOPRIGHT",-16,-198)
    toggle:SetFrameStrata("HIGH")
    if not Minimap then
        local mini=CreateFrame("Minimap","Minimap",UIParent)
        mini:SetWidth(130);mini:SetHeight(130);mini:SetPoint("TOPRIGHT",UIParent,"TOPRIGHT",-16,-62)
        mini:SetFrameStrata("MEDIUM");mini:EnableMouse(true);mini:EnableMouseWheel(true)
        mini:SetScript("OnMouseWheel",function() mini:SetZoom(mini:GetZoom()+(arg1>0 and 1 or -1)) end)
        mini:SetScript("OnMouseUp",function()
            local x,y=GetCursorPosition()
            mini:PingLocation(x-mini:GetLeft()-mini:GetWidth()/2,y-mini:GetBottom()-mini:GetHeight()/2)
        end)
    end
end
