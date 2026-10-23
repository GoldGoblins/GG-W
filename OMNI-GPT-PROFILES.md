# GG OmniGPT – gemensam lokal profilkatalog

GG AI Desktop använder de medföljande GPT-profilerna i `knowledge/web-gpts` som
ett gemensamt kunskaps- och beteendelager för både GROK och GPT. `GG-idekompassen`
är alltid den första tolkningslinsen. Övriga profiler väljs internt efter
uppgift; användaren behöver inte byta GPT eller motor.

Profilerna som ingår:

- `GG-idekompassen` – avsikt, hypoteser, researchgrind, tydliga frågor och
  Idékontrakt.
- `GG-AI-installator` – installation, Fedora, lokal AI, checkpoints, risk,
  backup och drift.
- `GG-Agentarkitekt-agentskapare` – lösningsstege, agentroller, handoffs,
  integrationer, risk och testning.
- `GG-Content-Studio` – Gold Goblins innehåll, produktfakta, säljbild och
  konceptbild.
- `GG-Marknadsföring` – marknadsstrategi, målgrupp, budskap, research och
  kvalitetssäkring.
- `GG-Metaarkitekt-gptskapare` – GPT-design, instruktioner, kunskapspaket och
  testsviter.
- `GG-Webmaster` – WordPress, WooCommerce, kod, SEO, UX, säkerhet och
  lokal-först webbdrift.

Runtime-routing och bounded context finns i
`backend/omni_gpt_profiles.py`. Källpaketen ingår i programkatalogen och läses
av båda motorerna från samma plats. Modulen läser Idékompassens kärna
varje relevant tur och hämtar därefter begränsade, uppgiftsrelevanta utdrag;
den stora Webmaster-källan dumpas inte blint in i varje prompt.

## Prioritet och säkerhet

Detta är användarskriven vägledning och referensmaterial. `AGENTS.md`, det
aktiva chatgodkännandet, Idékompassens säkerhetsgrindar och projektets körbara
kontrakt har alltid företräde. En profil kan aldrig ge behörighet. Credentials,
produktion, one.com, nätverk, sudo och skrivande åtgärder kräver det aktiva
`TASK_SCOPED`-godkännandet i chatten; hemliga värden får aldrig hamna i chat
eller loggar.

Om källkatalogen flyttas kan runtime söka på en annan plats via
`GG_GPT_KNOWLEDGE_ROOT`.
