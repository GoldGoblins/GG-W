# DAGoblin source-v3: sena original och beständig verifierbar topologi

## Ursprunglig avsikt

En långsam producent ska kunna arbeta i sin egen takt medan andra fortsätter.
Kontosignerade betalningar och producentens ursprungliga block ska behålla sin
identitet. SDK-konsensus och journalerna är informationskällan för CLI och
Desktop. Kvittens, blockurval och lyckad monetär exekvering är skilda saker.

## Fynd och beslut

Det riktiga source-v2-provet behöll två original med vardera 5 000 betalningar.
Andra producenter genomförde 15 000 betalningar och tre certifierade cuts.
Originalen avvisades därefter av både native CheckTx och insändningsvägen.
Det befintliga återförsöket behövde skapa nya producentoriginal över samma
kontosignaturer. Det räcker inte som generell lösning för en långsam producent.

Source-v3 inför därför en beständig, autentiserad indexering av samtliga valda
föräldrablock. Den ändrar inte äldre genesisers regler. Source-v1/v2 behåller
sina kodningar, epokregler och verifieringsvägar. Nya privata sessioner använder
source-v3 och en uttrycklig policy-v2. Ett befintligt source-v2-nät uppgraderas
inte genom att dess signerade genesis tolkas om.

## Protokollets förändring

Commitment-v3 innehåller `lineage_root`, som SDK:s certifikat binder till ett
innehållsadresserat AVL-träd över valda blockmetadata. Alla tillåtna föräldrar,
även äldre föräldrar från andra producenter, söks genom den roten. Att en
metadatafil finns på disk bevisar aldrig att blocket valts.

En cut avslutar fortfarande den aktiva perioden och dess begränsade index.
Producenternas egna huvuden och det beständiga topologiindexet består.
Signerad epok beskriver originalets signeringskontext; ett äldre original kan
väljas i en senare SDK-epok. Framtida epoker avvisas. Sekvens, föräldrar, rang,
producentsignatur och samtliga kontosignaturer kontrolleras fortfarande.
Okända föräldrar, fel rang, återspelade original och fel genesis avvisas.

Föräldrarangen behöver inte växa med andra producenters arbete eller antalet
cuts. Global monetär ordning finns i SDK-kvittots `order_index`.
Topologiindexets befintliga `index` är positionen inom exekveringsepoken och
presenteras inte som en global position. Originalets signerade epok skiljs
från kvittots faktiska exekveringsepok.

## Beständighet och resursgränser

Endast nya nåbara AVL-noder läggs till den synkrona LevelDB-batch som också
väljer journal och head. Efter commit ersätts trädet i RAM med diskreferenser.
Cachen rymmer högst 512 metadatanoder. En sökväg begränsas till 64 noder.
Denna indexering ersätter inte original, monetära kvitton eller SDK-historik.

Kall öppning verifierar alla original och monetära övergångar igen. Ett privat
tillfälligt diskindex räknar exakt de metadata som återspelningen härleder,
så även extra välformade men obundna poster avvisas. Saknade och skadade
poster repareras inte tyst. Arkivexport och arkivverifiering använder samma
slags begränsade cache och tillfälligt diskindex. Rekursiv städning kontrollerar
först den exakta privata sökvägen och följer inte en utbytt länk.

Diskförbrukning är en verklig kostnad. Historisk indexering och original har
ingen påstådd obegränsad lagringskapacitet eller skydd mot hel-disk-rollback.

## CLI, ägarskap och visning

Source-v3-journalen skapar inte ett nytt producentoriginal för samma sekvens
bara för att en cut passerat. En ändlig återhämtning skickar samma beständiga
bytes. Globalt stigande egna sekvenser och icke minskande signeringsepoker gör
att de befintliga SQLite-indexens begränsade slutdelar räcker för att hitta
återstående original, även över gränsen mellan aktiv journal och eget arkiv.

`lan.financial_resume` återupptar explicit det egna arbetet från journalen.
Vanlig `lan.resume` startar inte produktion. Gränserna 16 försök och 180 sekunders
arbetsbudget kvarstår, liksom separata stopp- och native-tidsgränser.
Kontosignaturer ändras inte och nonce/saldo används inte för att gissa blockurval.
Mottagaren kontrollerar själv den verkliga monetära exekveringen.

Blockägare är den verifierade producentnyckeln i den signerade medlemslistan.
Avsändaren av en betalning kan vara en annan kontoägare. Flera noder kan
verifiera samma block utan att ägarskapet dupliceras. CLI och Desktop läser
samma certifierade konton, producenter och begärda kvitton. En kompakt
SDK-attesterad vy påstår inte att den hämtat hela originalinnehållet.

## Verifiering och kvarvarande gränser

Modelltester använder verkliga konto- och producentsignaturer, men utgör inte
SDK-finalitet. De täcker gamla egna och andra producenters föräldrar, flera
cuts, oberoende ranger, okända/framtida/återspelade block och index över den
aktiva historikgränsen. Riktiga lagringstester täcker kall öppning, saknade,
skadade och extra metadata, osäker skrivkvittens och privat arkivstädning.

Ett separat test jämför Go-kodningen med lexikografiskt sorterad offentlig
JSON. Det fångade en felplacerad `lineage_root` i det första utkastet.
SDK-proven fångade också en kvarvarande version-2-spärr i Pythonadaptern.
Misslyckade försök och de första binärerna behålls som felsökningsunderlag.

Slutproven kräver riktiga, isolerade Windows- och Linux-SDK-nät med fyra
validatorer och en icke röstande källa. Den långsamma producentens arkiverade
original ska återöppnas kallt och väljas medan en separat ändlig ström fortsätter
skapa verkliga 5 000-betalningsblock och certifierade cuts. En cut måste bekräftas
av SDK; en inaktuell manuell cut-begäran får behöva hämtas på nytt efter samtidig
monetär progress. Export, full verifiering, återställning och UI måste stämma.

Linuxprovet som håller tre logiska Pythonägare i en enda testprocess redovisar
sin egen minnesbudget separat från varje native-nods oförändrade gränser.
Det är inte en fysisk Termux-mätning. Ghidra-granskningen omfattar endast den
faktiska parent-context-funktionen i den nybyggda kandidaten, inte hela binären.

Producentfördröjning och långsamma konsensusväljare är olika frågor. SDK behöver
fortfarande sitt föreskrivna quorum. Denna ändring bevisar varken slutkapaciteten,
generell kontohantering, publik mining/pool-ekonomi eller huvudnätsberedskap.
Uthållighet, fysisk acceptans, ekonomiska regler och oberoende säkerhetsgranskning
kvarstår. Hundratals block/s med 5 000 verkliga TX/block är fortfarande ett
mätkrav. Fullständig säkerhet eller att inga framtida ändringar behövs kan
inte garanteras genom intern granskning.
