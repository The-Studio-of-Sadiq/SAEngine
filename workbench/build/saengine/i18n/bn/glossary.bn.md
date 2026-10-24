# SAEngine Bangla (bn) glossary

Term choices for the Bangla UI of SAEngine. The aim is the Bangla a practising structural
engineer in Bangladesh reads and speaks: plain Bangla for ordinary UI words, and the English
technical words engineers actually use on site and in the office, written in Bangla script
where that is common and kept in Latin script where it is a code, symbol or abbreviation.
BNBC 2020 terms follow the code's own usage; where the Bangla of the code is unfamiliar in
practice, the English term in Bangla script is used.

Translators: when a term is missing here, add it before using it, so all screens agree.
Strings you are unsure of get `"status": "review"` and a `"note"` in `strings.bn.json`.

## Rules

| Rule | Example |
| --- | --- |
| Placeholders `{0}`, `{1}` … stay exactly as they are (each one once, any order). | `{0} of {1} selected` → `{1}টির মধ্যে {0}টি নির্বাচিত` |
| Units, symbols and numbers stay in Latin script: kN, kPa, MPa, mm, m, m², m³, kg, cft, °C, kW, kVA, %, ×, −, ≤, φ. | `{0} kPa (qa {1})` → `{0} kPa (qa {1})` |
| Digits stay Western (0–9), as in drawings, calculations and BNBC tables. | `Part 6` → `পার্ট 6` |
| Abbreviations and codes stay in Latin script: SAEngine, BNBC, ACI, ASTM, AISC, BOQ, FEM, BIM, CAD, MEP, HVAC, RC, RCC, SPT, CPT, PDF, DXF, DWG, IFC, JSON, CSV, ETABS, OpenSees, QGIS, OSM, AHU, DB, SDB, MDB, UPS, WWR, SHGC, LL, PL, PI, Mz, Vy … | `BOQ Export` → `BOQ এক্সপোর্ট` |
| Code clause references stay as written. | `BNBC 2020 Part 6 Sec 3.10.1.30` unchanged |
| Keyboard shortcuts and key names stay: Esc, Enter, Ctrl+S, Shift, Del, Tab. | `press Esc` → `Esc চাপুন` |
| Menu mnemonics: put the English mnemonic letter in brackets at the end. | `&&Restore` → `পুনরুদ্ধার(&&R)` |
| A numbered part (`05 Floor Plan`, `9 Substructure`) is a folder name the Navigator shows in English: keep it in English, case ending after a hyphen. An unnumbered part name (an editor title) is translated. | `in 04 Objects` → `04 Objects-এ`; `Floor Plan` (title) → `ফ্লোর প্ল্যান` |
| Command names typed at the floor-plan command line (`fill`, `mirror x`) stay in English. | |
| Counted nouns take -টি and no plural ending. | `{0} problems` → `{0}টি সমস্যা` |
| File names, setting ids, story/grid labels, quoted identifiers stay unchanged. | `'{0}'`, `A, B, C`, `project.saengine.json` |
| Commands (buttons, menu items) use the polite imperative (-উন) or a noun. | `Open Project` → `প্রজেক্ট খুলুন` |
| Ellipsis `...` and trailing punctuation follow the English. | `Import...` → `ইমপোর্ট...` |
| The Bangla full stop `।` ends sentences; keep `:` `;` `,` as in English. | |

## UI words

| English | Bangla | Note |
| --- | --- | --- |
| Add | যোগ করুন | |
| Apply | প্রয়োগ করুন | |
| Browse | ব্রাউজ করুন | |
| Cancel | বাতিল | |
| Close | বন্ধ করুন | |
| Copy | কপি | |
| Create | তৈরি করুন | |
| Delete / Remove | মুছুন / সরান | delete data → মুছুন; remove from a list → সরান |
| Edit | সম্পাদনা | |
| Export | এক্সপোর্ট | |
| File / Folder | ফাইল / ফোল্ডার | |
| Import | ইমপোর্ট | |
| Name | নাম | |
| New | নতুন | |
| None | নেই | |
| Open | খুলুন | |
| Preview | প্রিভিউ | |
| Project | প্রজেক্ট | engineers say প্রজেক্ট; প্রকল্প reads as a government scheme |
| Properties | বৈশিষ্ট্য | |
| Refresh | রিফ্রেশ | |
| Rename | নাম পরিবর্তন | |
| Restore | পুনরুদ্ধার | |
| Run | রান করুন | analysis runs; চালান also acceptable |
| Save | সংরক্ষণ করুন | |
| Search / Filter | খুঁজুন / ফিল্টার | |
| Select | নির্বাচন করুন | selected → নির্বাচিত |
| Settings | সেটিংস | |
| Show / Hide | দেখান / লুকান | |
| Start page | শুরুর পাতা | |
| Undo / Redo | আনডু / রিডু | |
| Version | ভার্সন | issued version → ইস্যু করা ভার্সন |
| Warning / Error | সতর্কতা / ত্রুটি | |

## Building and structure

| English | Bangla | Note |
| --- | --- | --- |
| Building | ভবন | |
| Story / storey | তলা | |
| Floor | ফ্লোর | floor of a room/slab; "Floor Plan" → ফ্লোর প্ল্যান |
| Typical floor | টিপিক্যাল ফ্লোর | |
| Roof | ছাদ | |
| Grid / grid line | গ্রিড / গ্রিড লাইন | |
| Column | কলাম | |
| Beam | বিম | |
| Slab | স্ল্যাব | |
| Wall / shear wall | দেয়াল / শিয়ার ওয়াল | |
| Coupling beam | কাপলিং বিম | |
| Stair | সিঁড়ি | |
| Lift / elevator | লিফট | |
| Opening | ওপেনিং | |
| Member | মেম্বার | |
| Object type | অবজেক্ট টাইপ | |
| Section | সেকশন | cross-section; a section of a document → অংশ |
| Frame / moment frame | ফ্রেম / মোমেন্ট ফ্রেম | Ordinary/Intermediate/Special moment frame → অর্ডিনারি/ইন্টারমিডিয়েট/স্পেশাল মোমেন্ট ফ্রেম |
| Structural system | স্ট্রাকচারাল সিস্টেম | |
| Material | ম্যাটেরিয়াল | |
| Concrete | কংক্রিট | |
| Steel / reinforcement / bar / rebar | স্টিল / রিইনফোর্সমেন্ট / রড / রড | BD sites say রড |
| Stirrup / tie | স্টিরাপ / টাই | |
| Clear cover | ক্লিয়ার কভার | |
| Brick / cement / sand / stone chips | ইট / সিমেন্ট / বালি / পাথর কুচি | |
| Mix (concrete) | মিক্স | e.g. 1:1.5:3 মিক্স |
| Part (of the project, Navigator) | পার্ট | the numbered parts 01 … 09 |

## Analysis and design

| English | Bangla | Note |
| --- | --- | --- |
| Analysis | অ্যানালাইসিস | |
| Design | ডিজাইন | |
| Check (design check) | চেক | |
| Load / load case / load combination | লোড / লোড কেস / লোড কম্বিনেশন | |
| Dead / live / wind / seismic load | ডেড / লাইভ / উইন্ড / সিসমিক লোড | |
| Earthquake | ভূমিকম্প | |
| Seismic zone | সিসমিক জোন | |
| Moment / shear / axial force / torsion | মোমেন্ট / শিয়ার / অক্ষীয় বল / টর্শন | |
| Deflection / drift | ডিফ্লেকশন / ড্রিফট | |
| Period / mode | পিরিয়ড / মোড | |
| Utilisation | ইউটিলাইজেশন | |
| Governing | নিয়ন্ত্রক | "governed by {0}" → "{0} দ্বারা নিয়ন্ত্রিত" |
| Capacity / demand | ক্যাপাসিটি / ডিমান্ড | |
| Passes / fails | পাস / ফেল | |
| Model / analysis model | মডেল / অ্যানালাইসিস মডেল | |
| Results | ফলাফল | |
| Mesh / node / element | মেশ / নোড / এলিমেন্ট | |
| Support / fixed / pinned | সাপোর্ট / ফিক্সড / পিনড | |
| Second-order analysis | সেকেন্ড-অর্ডার অ্যানালাইসিস | |
| Detailing | ডিটেইলিং | |
| Ductile | ডাকটাইল | |

## Soil and foundations

| English | Bangla | Note |
| --- | --- | --- |
| Soil / soil investigation | মাটি / সয়েল ইনভেস্টিগেশন | |
| Site | সাইট | |
| Borehole | বোরহোল | |
| Stratum / strata / layer | স্তর | |
| Groundwater table | ভূগর্ভস্থ পানির স্তর | |
| SPT N-value / blow count | SPT N-মান / ব্লো কাউন্ট | |
| Bearing capacity | বিয়ারিং ক্যাপাসিটি | |
| Settlement | সেটেলমেন্ট | |
| Liquefaction | লিকুইফ্যাকশন | |
| Lab test / specimen / sample | ল্যাব টেস্ট / নমুনা / নমুনা | |
| Plasticity index / liquid limit / plastic limit | প্লাস্টিসিটি ইনডেক্স / লিকুইড লিমিট / প্লাস্টিক লিমিট | |
| Foundation | ফাউন্ডেশন | |
| Substructure | সাবস্ট্রাকচার | |
| Footing / isolated / combined | ফুটিং / আইসোলেটেড / কম্বাইন্ড | |
| Mat / raft | ম্যাট / র‍্যাফট | |
| Pile / pile cap / driven / bored | পাইল / পাইল ক্যাপ / ড্রিভেন / বোরড | |
| Grade beam / tie beam | গ্রেড বিম / টাই বিম | |
| Retaining wall | রিটেইনিং ওয়াল | |
| Factor of safety | ফ্যাক্টর অব সেফটি | |

## Drawings, quantities and reports

| English | Bangla | Note |
| --- | --- | --- |
| Drawing / sheet | ড্রয়িং / শিট | |
| Plan / elevation / section | প্ল্যান / এলিভেশন / সেকশন | |
| Dimension | ডাইমেনশন | |
| Layer | লেয়ার | CAD layer; soil layer → স্তর |
| BOQ (bill of quantities) | BOQ | |
| Quantity / rate / amount / cost | পরিমাণ / দর / টাকার পরিমাণ / খরচ | |
| Report | রিপোর্ট | |
| Issue (a version) | ইস্যু | |

## MEP

| English | Bangla | Note |
| --- | --- | --- |
| Plumbing / electrical / HVAC | প্লাম্বিং / ইলেকট্রিক্যাল / HVAC | |
| Fixture | ফিক্সচার | |
| Water supply / drainage / sewer | পানি সরবরাহ / ড্রেনেজ / স্যুয়ার | |
| Tank (overhead / underground) | ট্যাংক (ওভারহেড / আন্ডারগ্রাউন্ড) | |
| Pump / pipe / riser | পাম্প / পাইপ / রাইজার | |
| Duct / sleeve / shaft | ডাক্ট / স্লিভ / শ্যাফট | |
| Clash | ক্ল্যাশ | |
| Cooling load | কুলিং লোড | |
| Circuit / feeder / breaker / cable | সার্কিট / ফিডার / ব্রেকার / ক্যাবল | |
| Substation / generator / transformer | সাবস্টেশন / জেনারেটর / ট্রান্সফর্মার | |
| Connected load / maximum demand | কানেক্টেড লোড / ম্যাক্সিমাম ডিমান্ড | |
| Occupancy | অকুপেন্সি | BNBC occupancy classes keep their letters (A, B …) |

## Added during the first translation

| English | Bangla | Note |
| --- | --- | --- |
| Building Model / Structural Model | বিল্ডিং মডেল / স্ট্রাকচারাল মডেল | editor names |
| Up to date / out of date (stale) | হালনাগাদ / পুরনো | |
| Run All | সব রান করুন | |
| Generate / regenerate | জেনারেট করুন / আবার জেনারেট করুন | |
| Equipment / plant | ইকুইপমেন্ট / প্ল্যান্ট | |
| Supplier | সাপ্লায়ার | |
| Backend | ব্যাকএন্ড | |
| Coordination | কো-অর্ডিনেশন | |
| Override | ওভাররাইড | |
| Allowable (bearing pressure) | অ্যালাউয়েবল | |
| Importance factor | ইম্পর্ট্যান্স ফ্যাক্টর | |
| Formwork | ফর্মওয়ার্ক | শাটারিং is common on site; review |
| Masonry (brick) / earthwork | ইটের গাঁথুনি / মাটির কাজ | |
| Base shear / seismic weight | বেস শিয়ার / সিসমিক ওজন | |
| Response spectrum / equivalent static | রেসপন্স স্পেকট্রাম / ইকুইভ্যালেন্ট স্ট্যাটিক | |
| Seismic Design Category / site class | সিসমিক ডিজাইন ক্যাটাগরি / সাইট ক্লাস | |
| Response reduction / overstrength factor | রেসপন্স রিডাকশন / ওভারস্ট্রেংথ ফ্যাক্টর | |
| Basic wind speed / exposure | বেসিক উইন্ড স্পিড / উইন্ড এক্সপোজার | |
| Slenderness / unbraced length / effective length factor | স্লেন্ডারনেস / আনব্রেসড লেংথ / ইফেক্টিভ লেংথ ফ্যাক্টর | |
| Sway / non-sway; moment magnifier | সোয়ে / নন-সোয়ে; মোমেন্ট ম্যাগনিফায়ার | |
| Boundary element / hoop / splice | বাউন্ডারি এলিমেন্ট / হুপ / স্প্লাইস | |
| Strong column–weak beam | স্ট্রং কলাম / উইক বিম | |
| Compact / noncompact / slender (steel) | কমপ্যাক্ট / নন-কমপ্যাক্ট / স্লেন্ডার | |
| Lateral-torsional buckling | ল্যাটারাল-টর্শনাল বাকলিং | |
| Flange / web / gusset / end plate | ফ্ল্যাঞ্জ / ওয়েব / গাসেট / এন্ড প্লেট | |
| Flight / landing / riser / going | ফ্লাইট / ল্যান্ডিং / রাইজার / ট্রেড | |
| Soil springs / fixed base | সয়েল স্প্রিং / ফিক্সড বেস | |
| Unit weight / undrained shear strength | ইউনিট ওয়েট / আনড্রেইনড শিয়ার স্ট্রেংথ | |
| Cohesion / friction angle | কোহেশন / ফ্রিকশন অ্যাঙ্গেল | |
| Void ratio / compression index / consolidation | ভয়েড রেশিও / কম্প্রেশন ইনডেক্স / কনসলিডেশন | |
| Clay / silt / gravel / fill / rock | ক্লে / সিল্ট / গ্র্যাভেল / ফিল / শিলা | sand → বালি |
| Skin friction / end bearing / uplift | স্কিন ফ্রিকশন / এন্ড বিয়ারিং / আপলিফট | |
| Punching / one-way shear | পাঞ্চিং / ওয়ান-ওয়ে শিয়ার | |
| Subgrade modulus | সাবগ্রেড মডুলাস | |
| Founding level / ground level | ফাউন্ডিং লেভেল / গ্রাউন্ড লেভেল | |
| Latitude / longitude / map | অক্ষাংশ / দ্রাঘিমাংশ / মানচিত্র | |
| Septic tank / soak well | সেপটিক ট্যাংক / সোক ওয়েল | |
| Stack / riser / rainwater leader | স্ট্যাক / রাইজার / রেইনওয়াটার লিডার | RWP common on site; review |
| Residual head / pump duty | রেসিডুয়াল হেড / পাম্প ডিউটি | |
| Chiller / AHU / FCU / cooling tower | চিলার / এয়ার হ্যান্ডলিং ইউনিট / ফ্যান কয়েল ইউনিট / কুলিং টাওয়ার | |
| Sensible / latent; dry / wet bulb | সেনসিবল / ল্যাটেন্ট; ড্রাই / ওয়েট বাল্ব | |
| Envelope / glazing / shading | এনভেলপ / গ্লেজিং / শেডিং | |
| Cable tray / busbar trunking / switchgear | ক্যাবল ট্রে / বাসবার ট্রাংকিং / সুইচগিয়ার | |
| Earthing / lightning protection / down conductor | আর্থিং / লাইটনিং প্রোটেকশন / ডাউন কন্ডাক্টর | |
| Title block / schedule / bar bending schedule | টাইটেল ব্লক / শিডিউল / বার বেন্ডিং শিডিউল | |
| Revision / scale | রিভিশন / স্কেল | |
| Status pills ok / check / fails | ঠিক আছে / চেক করুন / ফেল | |
