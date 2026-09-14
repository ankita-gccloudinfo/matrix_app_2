# MATRIX System — RAG Knowledge Base (Qdrant Optimized)

**System Full Name:** MATRIX — Monitoring, Analytics, Trends, Redressal & Intelligence through Social Media eXploration  
**Organization:** Uttar Pradesh Police (UP Police)  
**Purpose:** Real-time social media monitoring, incident analysis, and rapid response coordination across all 75 districts of Uttar Pradesh, India.  
**Powered By:** Goodwill Communication  

> Each section in this document is a self-contained semantic chunk. It is structured to match both formal English queries and casual Hindi/Hinglish queries for optimal RAG retrieval.

---

## Module 1: System Login & Authentication (Login Kaise Karen)

**Concept:** MATRIX is a secured web portal. Only authorized UP Police officers can log in. There are 4 hierarchical access levels.

**Primary Login URL (Main Login Page):**
- `https://matrixupp.com/sc/dgpDashboard_2`
- This is the **main entry point** (homepage) of the MATRIX system.
- This page is also called the "DGP Dashboard Login Page".

**4 Login Levels (4 Login Star / User Types):**
1. **HEADQUARTERS (HQ)** — DGP level, highest authority, full system access.
2. **ZONE_POL** — Zonal Police Officers (e.g., Lucknow Zone, Meerut Zone).
3. **RANGE_POL** — Range-level Police Officers (e.g., Agra Range).
4. **DIS_POL** — District-level Police Officers, SSP/SP level.

**Authentication Process:**
- User selects their role tab (HQ, Zone, Range, District).
- Enters username (dynamically populated from a dropdown based on role).
- Enters password.
- Google reCAPTCHA v3 bot protection is applied.
- First-time users must complete a profile with Email OTP verification.

**Password Reset URL:** `https://matrixupp.com/sc/resetPassword`  
**Edit Profile URL:** `https://matrixupp.com/sc/editProfile`  
**Active Sessions URL:** `https://matrixupp.com/sc/active_session`  
**Login History / Audit Log URL:** `https://matrixupp.com/sc/login_history`  
**User Management URL:** `https://matrixupp.com/sc/User`  

**Hindi/Hinglish Query Variants (for semantic matching):**
- "matrix mein login kaise karte hain"
- "DGP UP ka login URL kya hai"
- "matrix ka main URL kya hai"
- "password kaise reset karein"
- "login nahi ho raha kya karein"
- "user kaise banate hain"

---

## Module 2: Headquarters (HQ) Dashboard — DGP Dashboard

**Concept:** After login at the HQ level, users land on the main Headquarter Dashboard. This shows a bird's-eye view of all social media activity across UP.

**URL:** `https://matrixupp.com/sc/dgpDashboard_2`

**Dashboard Panes (Sections within the URL using `#` anchors):**
- `https://matrixupp.com/sc/dgpDashboard_2#categoryPane` — Category-wise post breakdown
- `https://matrixupp.com/sc/dgpDashboard_2#districtPane` — District-wise post view
- `https://matrixupp.com/sc/dgpDashboard_2#zonePane` — Zone-wise post view
- `https://matrixupp.com/sc/dgpDashboard_2#rangePane` — Range-wise post view
- `https://matrixupp.com/sc/dgpDashboard_2#commissioneratePane` — Commissionerate view

**What does the Dashboard show?**
- Total posts captured based on keywords for UP Police.
- Platform-wise breakdown: X (Twitter), Facebook, Instagram, WhatsApp, YouTube, Web News.
- Filtering by: Status (Unread / Read / All), Time Period (Current Day, Last 7 Days, Last 30 Days, Custom Date).

**Standard Dashboard URL (District/Zone/Range Level):** `https://matrixupp.com/sc/dashboard`

**Hindi/Hinglish Query Variants:**
- "HQ dashboard kya hai"
- "DGP dashboard ka URL kya hai"
- "main dashboard kahan hai"
- "total posts kaise dekhein"

---

## Module 3: Tagged Posts Section (Tags — DGP UP, GOVT OF INDIA, etc.)

**Concept:** On the HQ Dashboard (`https://matrixupp.com/sc/dgpDashboard_2`), there is a **TAGGED POSTS** section. These are special buckets that automatically collect posts mentioning specific high-priority entities. They are **not separate pages** — they are interactive cards on the main dashboard.

**Available Tags and Their Meaning:**
- **DGP UP** — Posts directly relevant to the Director General of Police, UP.
- **GOVT OF INDIA** — Posts related to the Central Government of India.
- **GOVT OF UP** — Posts related to the UP State Government.
- **UP POLICE** — Posts mentioning UP Police in general.
- **UP 112** — Posts mentioning the UP emergency helpline 112.
- **WPL 1090** — Posts mentioning the Women Power Line 1090.
- **POLITICAL HANDLES** — Posts from tracked political accounts.
- **NEWS HANDLES** — Posts from tracked news channel accounts.
- **ZONE** — Zone-level tagged content.
- **RANGE** — Range-level tagged content.
- **COMMISSIONERATE** — Commissionerate-level tagged content.
- **DISTRICT** — District-level tagged content.

**URL for All Tags:** `https://matrixupp.com/sc/dgpDashboard_2`
**Tag Monitoring Management URL:** `https://matrixupp.com/sc/tagMonitoringProfiles`

**Hindi/Hinglish Query Variants:**
- "DGP UP tag ka URL kya hai"
- "GOVT OF INDIA tag kahan hai"
- "UP POLICE tag ka kya matlab hai"
- "tagged posts kya hote hain"
- "WPL 1090 tag kahan dikhta hai"
- "tagged section ka URL kya hai"

---

## Module 4: Monitored Profile Section (Monitored Profiles)

**Concept:** The MONITORED PROFILE section is on the right side of the HQ Dashboard. Instead of just tracking keywords, this section tracks **all activity from specific, pre-defined social media handles** (accounts).

**URL:** `https://matrixupp.com/sc/postMonitoringProfiles`  
**Tag-based Profile Tracking URL:** `https://matrixupp.com/sc/tagMonitoringProfiles`  
**Connected Accounts URL:** `https://matrixupp.com/sc/connectedAccounts`  
**Profile Detail View URL:** `https://matrixupp.com/sc/profileView`  

**Categories Inside Monitored Profile:**
- **NEWS HANDLES** — Official accounts of news channels and publications.
- **JOURNALIST** — Individual accounts of prominent reporters.
- **POLITICAL HANDLES** — Politicians, political parties, political influencers.

**How it works:** The system continuously monitors posts from these pre-defined accounts. Numbers shown next to each category = volume of recent activity from those tracked accounts.

**Hindi/Hinglish Query Variants:**
- "monitored profile mein kya hota hai"
- "kaunse accounts monitor hote hain"
- "journalist accounts kaise track karein"
- "political handles monitor karna"
- "news channel accounts tracking"
- "profile view ka URL kya hai"

---

## Module 5: Ticket Lifecycle — 4 Stages / 4 Charan (Ticket Status)

**Concept:** Every incident identified on social media is converted into a **Ticket**. The ticket goes through a mandatory 4-stage (4 charan) lifecycle. Different authority levels are responsible for each stage.

**Main Ticket Dashboard URL:** `https://matrixupp.com/sc/ticketDashboard3`

**The 4 Stages (4 Charan) with their URLs:**

### Stage 1: Assigned (Saunpa Gaya)
- **What it means:** The system auto-assigns a ticket to the relevant district based on the location tag in the post.
- **URL:** `https://matrixupp.com/sc/showAllTickets`
- **Responsible:** System (automatic)

### Stage 2: In Progress (Kaam Chal Raha Hai)
- **What it means:** The district officer is actively investigating and working on the ticket.
- **URL:** `https://matrixupp.com/sc/showAllprogressTickets`
- **Responsible:** District (DIS_POL)

### Stage 3: Closed (Band Kiya / Khatam)
- **What it means:** The district officer has resolved the issue and marked the ticket as closed. It now awaits verification from higher authority.
- **URL:** `https://matrixupp.com/sc/ticketClosedAndVerification`
- **Responsible:** District (DIS_POL)

### Stage 4: Verified (Sahi Mana Gaya / Verify)
- **What it means:** A senior officer (HQ / Zone / Range) has reviewed the district's closure and verified it as genuinely resolved.
- **URL:** `https://matrixupp.com/sc/verifiedTicket`
- **Responsible:** HQ / Zone / Range

**Additional Ticket States (beyond the 4 main stages):**
- **False Closure (Galat Tarike Se Band):** If HQ finds a district closed a ticket incorrectly without resolution.
  - **URL:** `https://matrixupp.com/sc/falseClosureTicket`
- **Discarded (Raddi / Hataya Gaya):** Ticket marked as a false alarm or irrelevant.
  - **URL:** `https://matrixupp.com/sc/showDiscardTicket`
- **Transfer (Doosri Jagah Bhejna):** Post/ticket transferred to a different district.
  - **URL:** `https://matrixupp.com/sc/transfer-post`

**Ticket Lifecycle Flow:**
`Auto Assigned → In Progress (District) → Closed by District → Verified by HQ/Zone/Range`

**Report Upload per Ticket:**
Districts must upload the following reports to each ticket:
- Internal Report
- Intelligence Report
- CCC Report
- TV Scroll

**Hindi/Hinglish Query Variants:**
- "ticket status kya hai"
- "ticket ke 4 charan kya hain"
- "ticket ka URL kya hai"
- "4 stages of ticket kya hote hain"
- "ticket kaise verify karte hain"
- "galat ticket close ho gaya to kya karein"
- "ticket discard kaise karein"
- "in progress ticket kahan dikhta hai"
- "ticket transfer kaise karein"

---

## Module 6: Post Monitoring & Filtered Post View (allPostTable)

**Concept:** The `allPostTable` is the core post-browsing screen. It dynamically shows filtered social media posts based on location, topic, status, and time. This is accessed by clicking on any category tile, district, or zone on the dashboard.

**Base URL:** `https://matrixupp.com/sc/allPostTable`

**Filter by District (Jile Ke Hisab Se):**
- `https://matrixupp.com/sc/allPostTable?district=Lucknow&status=unread&fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD`
- Replace `Lucknow` with any UP district name.
- All 75 UP districts are supported: Agra, Aligarh, Ambedkar Nagar, Amethi, Amroha, Auraiya, Ayodhya, Azamgarh, Baghpat, Bahraich, Ballia, Balrampur, Banda, Barabanki, Bareilly, Basti, Bhadohi, Bijnor, Budaun, Bulandshahr, Chandauli, Chitrakoot, Deoria, Etah, Etawah, Farrukhabad, Fatehpur, Firozabad, Gautam Buddha Nagar, Ghaziabad, Ghazipur, Gonda, Gorakhpur, Hamirpur, Hapur, Hardoi, Hathras, Jalaun, Jaunpur, Jhansi, Kannauj, Kanpur Dehat, Kanpur, Kasganj, Kaushambi, Kushinagar, Lakhimpur Kheri, Lalitpur, Lucknow, Maharajganj, Mahoba, Mainpuri, Mathura, Mau, Meerut, Mirzapur, Moradabad, Muzaffarnagar, Pilibhit, Pratapgarh, Prayagraj, Raebareli, Rampur, Saharanpur, Sambhal, Sant Kabir Nagar, Shahjahanpur, Shamli, Shravasti, Siddharthnagar, Sitapur, Sonbhadra, Sultanpur, Unnao, Varanasi.

**Filter by Range (Range Ke Hisab Se):**
- `https://matrixupp.com/sc/allPostTable?range=Lucknow Range&status=unread&fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD`
- Available Ranges: Agra Range, Aligarh Range, Ayodhya Range, Azamgarh Range, Bareilly Range, Basti Range, Chitrakoot Range, Devipatan Range, Gorakhpur Range, Jhansi Range, Kanpur Range, Lucknow Range, Meerut Range, Mirzapur Range, Moradabad Range, Prayagraj Range, Saharanpur Range, Varanasi Range.

**Filter by Zone (Zone Ke Hisab Se):**
- `https://matrixupp.com/sc/allPostTable?zone=Lucknow Zone&status=unread&fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD`
- Available Zones: Agra Zone, Bareilly Zone, Gorakhpur Zone, Kanpur Zone, Lucknow Zone, Meerut Zone, Prayagraj Zone, Varanasi Zone.

**Filter by Sub-Category (Upcategory / Topic Se):**
- `https://matrixupp.com/sc/allPostTable?subCategory=MURDER&status=unread&fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD`
- All Monitored Sub-Categories: ABUSIVE, ACCIDENT, ANTI NATIONAL ACTIVITIES, APPRECIATION, ASSAULT, BLAST / EXPLOSION, BOGUS VOTING, BOOTH CAPTURING, BOOTH FACILITIES ISSUES, BOOTH MACHINE ISSUES, BOOTH OFFICIALS COMPLAINTS, CASTE, CASTE-BASED HATE SPEECH, CHARACTER VERIFICATION, COMMUNAL, COMMUNAL HATE SPEECH, CORRUPTION OF OTHER DEPARTMENTS, COW SLAUGHTER, CRIME AGAINST ANIMAL / PETA, CRIME AGAINST MINOR, CRIME AGAINST WOMEN, CRITICISM, DIGITAL ARREST, DRUG POSSESSION, DRUG TRAFFICKING, ELECTORAL DISPUTES, FAKE NEWS, FINANCIAL FRAUD, FIR RELATED COMPLAINTS, FIRE EMERGENCY, GENERAL COMPLAINTS, HIT&RUN, KANWAD, KIDNAPPING, LAND DISPUTES, LOOT, LOVE JIHAAD, MCC VIOLATIONS, MEDICAL EMERGENCY, MISSING PERSONS, MURDER, NATURAL DISASTER, OTHER CYBER CRIME, OTHERS, OTHERS TRAFFIC ISSUES, PASSPORT RELATED, POLICE CORRUPTION, POLICE MISCONDUCT, POLICE NEGLIGENCE, POLITICALLY MOTIVATED HATE SPEECH, POSITIVE, PROTEST, RAILWAY CRIME, RAILWAY EMERGENCY, RELIGIOUS CONVERSIONS, RIOT, ROBBERY, RUMOURS, SENSATIONAL CRIME, STRIKE, TERRORIST, THEFT, TRAFFIC JAM, TROLLING, VIRAL CONTENT.

**URL Query Parameters:**
- `district=` — Filter by specific district name
- `range=` — Filter by range name
- `zone=` — Filter by zone name
- `subCategory=` — Filter by incident type
- `status=unread` — Only unread posts
- `status=read` — Only read posts
- `fromDate=YYYY-MM-DD` — Start date
- `toDate=YYYY-MM-DD` — End date

**Post Detail Features (on the allPostTable page):**
- Mention, Hashtag, and Link highlighting in distinct colors
- Source platform filter (X, Facebook, Instagram, YouTube, WhatsApp, Web News)
- Read/Unread and Reply/Not Reply status filter
- Table columns: User Profile info, Post Stats (RT, Like, View), Action Buttons, Source, Sub Category, Attachments

**Hindi/Hinglish Query Variants:**
- "Lucknow ke posts kaise dekhein"
- "unread posts kahan hain"
- "MURDER category ke posts ka URL kya hai"
- "Meerut zone ke posts filter karna"
- "FAKE NEWS sub-category ka URL kya hai"
- "crime against women posts kaise dekhein"

---

## Module 7: Post Action Buttons (Post Par Kya Kar Sakte Hain)

**Concept:** Every post in the allPostTable has 7 action buttons available for officers to take action.

**The 7 Action Buttons:**
1. **Bookmark** — Save important posts for future reference. Creates bookmark groups. Download bookmark reports.
   - URL: `https://matrixupp.com/sc/bookmark`
2. **Notes** — Add internal remarks visible only within the department (HQ ↔ District).
3. **Notify** — Send post alert to a superior officer (e.g., notify Range / Zone HQ).
4. **Mark as Read** — Update post status to reduce unread count.
5. **Reply** — Respond using pre-defined reply templates. Works on tagged posts automatically. Untagged posts require manual reply on the platform.
   - URL for managing replies: `https://matrixupp.com/sc/addReply`
6. **Transfer** — Move a post to a different topic, or raise a district transfer request.
   - URL: `https://matrixupp.com/sc/transfer-post`
7. **Raise Change Request** — Submit a request if the post was assigned to the wrong district.

**Additional Action Features:**
- **Update Metric** — Fetch latest engagement stats (likes, comments, shares, views) for a post. Exclusive to HQ.
- **Fetch Reply** — Retrieve thread replies to a post. Configurable depth: Shallow (official replies only) or Deep (public replies).

**Bookmark Reporting:** Generate Topic Report, Index Report, or Full Report containing FIR details, incident descriptions, and assailant information.

**Hindi/Hinglish Query Variants:**
- "post ko bookmark kaise karein"
- "post par notes kaise lagayein"
- "superior officer ko notify kaise karein"
- "post reply kaise dein"
- "post transfer kaise karein"
- "galat district mein post aayi to kya karein"
- "post ke like/view kaise update karein"
- "7 action buttons kya hain"

---

## Module 8: Reply System & Templates (Reply Kaise Dein)

**Concept:** Officers can reply to social media posts directly from MATRIX using pre-configured templates. The system has 3 tiers of reply methods.

**Reply Management URL:** `https://matrixupp.com/sc/addReply`  
**Reply Category URL:** `https://matrixupp.com/sc/replyCategory`  
**Reaction Tracking URL:** `https://matrixupp.com/sc/reaction`  
**Twitter Replies Report URL:** `https://matrixupp.com/sc/twitter-replies-report`  
**Twitter Reporting URL:** `https://matrixupp.com/sc/twitterReporitng`  

**Reply Template Management:**
- Create via Admin Utilities section.
- Define Visibility Scope (who can use this template).
- Define Reply Category (e.g., Crime, Traffic).
- Max 280 characters per template.

**3-Tier Reply Mode (Recommended):**
- **Tier 1:** Fast API — Direct API call to post the reply (fastest).
- **Tier 2:** Extension Automation — If API fails, the browser extension handles it.
- **Tier 3:** Manual Fallback — If both fail, officer replies manually on the platform.

**Browser Extension Requirement:**
- For 3-Tier Mode: Install "Twitter Reply Automation - Parallel Mode" from the Chrome Web Store.
- Extension status indicator: **Green = Connected & Active**, **Red = Offline/Disconnected**.
- Extension Setup Guide URL: `https://matrixupp.com/sc/connectedAccounts`

**Reaction Categories (Pratikriya):**
- Trolling, Criticism, Abusive, Appreciation

**Hindi/Hinglish Query Variants:**
- "reply template kaise banayein"
- "3 tier mode kya hai"
- "extension kaise lagayein"
- "extension green nahi ho rahi"
- "auto reply kaise karein"
- "twitter par reply karna"
- "reaction analysis kya hai"

---

## Module 9: Search System (Search Kaise Karein)

**Concept:** MATRIX has two search modes — Simple Search and Advanced Search — to find any post across all monitored platforms.

**Simple Search:**
- Search posts by keyword across all platforms and date ranges.
- URL: `https://matrixupp.com/sc/allTopics` (accessed via search tab)

**Advanced Search:**
- Apply complex multi-condition filters.
- Use **AND logic** (all keywords must match) or **OR logic** (any keyword can match).
- Filter by: Platform, Specific Author Handles, Districts, Date Range.
- Export results as Excel (.xlsx) or PDF.

**Search Query Groups URL:** `https://matrixupp.com/sc/groupKeyword`

**Instagram-specific Search:**
- `https://matrixupp.com/sc/instagramLiveSearch`
- `https://matrixupp.com/sc/instaHashtag`

**Twitter Live API Search URL:** `https://matrixupp.com/sc/twitterReporitng`

**Archival Search (Historical Data):**
- `https://matrixupp.com/sc/archival`
- `https://matrixupp.com/sc/archival/view`

**Hindi/Hinglish Query Variants:**
- "post search kaise karein"
- "advanced search kya hai"
- "AND OR search kya hota hai"
- "specific keyword ka post kaise dhundhein"
- "instagram hashtag search karna"
- "purana data kaise dekhein"
- "search result export kaise karein"

---

## Module 10: Topic Matrix & Automated Ticketing (Ticket Kaise Banta Hai)

**Concept:** The Topic Matrix is the intelligence backbone of MATRIX. It automatically groups related posts on a single subject into a consolidated "Topic", which then becomes an actionable Ticket routed to the right district.

**URL:** `https://matrixupp.com/sc/allTopics`  
**DGP-level Topic View URL:** `https://matrixupp.com/sc/allTopicsDgp`  
**Pinned High-Priority Topics URL:** `https://matrixupp.com/sc/pinnedTopicView`  
**Influencer View of Topics URL:** `https://matrixupp.com/sc/influencerViewTopicTable`  
**Non-Influencer View of Topics URL:** `https://matrixupp.com/sc/nonInfluencerViewTopicTable`  

**How Topics become Tickets:**
1. System detects multiple posts about the same incident.
2. Groups them into a single "Topic" automatically.
3. Assigns a unique **Ticket Number**.
4. Routes the ticket to the relevant district.
5. Performs **Sentiment Analysis** on the grouped posts.
6. District receives the ticket and begins working (In Progress).

**Topic Management Features:**
- Merge two similar topics manually (Start Merge / Merge Suggestion).
- Broad Categories (Grievance, Crime, Traffic, etc.).
- Summary View: one page with all reports, documents, and sentiment for a topic.

**Hindi/Hinglish Query Variants:**
- "ticket kaise banta hai"
- "topic matrix kya hai"
- "automatic ticket generation kaise hoti hai"
- "topic merge kaise karein"
- "pinned topic kya hota hai"
- "influencer topic view kya hai"

---

## Module 11: Analytics & Reporting (Analytics / Report)

**Concept:** MATRIX provides rich dashboards for deep analysis of all captured social media data.

**Sentiment Analysis Dashboard URL:** `https://matrixupp.com/sc/sentimentAnalysisDashboard`  
**Monitoring Analysis URL:** `https://matrixupp.com/sc/monitoringAnalayis`  
**Trend Report URL:** `https://matrixupp.com/sc/trendReportOneView`  
**KPI Metrics Dashboard URL:** `https://matrixupp.com/sc/kpimatrixDaskborad`  
**Common Feature Report URL:** `https://matrixupp.com/sc/commonFeatureReport`  
**District Internal Report View URL:** `https://matrixupp.com/sc/districtInternalReportView`  
**Newspaper Cutting Archive URL:** `https://matrixupp.com/sc/newsPaperCuttingPage`  
**Geospatial Map URL:** `https://matrixupp.com/sc/map`  
**Post Report URL:** `https://matrixupp.com/sc/postReport`  
**Pinned Topic Report URL:** `https://matrixupp.com/sc/pinnedTopicView`  

**Analytics Features:**

### Sentiment & Emotion Analysis
- Classifies posts: Neutral, Happy, Sad, Angry, Fearful, Disgusted, Surprised, Frustrated.
- Shows emotion percentages and Emotion Timeline (hourly graph).

### Trend Report
- Platform statistics (Twitter, WhatsApp, Facebook, Instagram, YouTube).
- Posts Hourly Trend line chart.
- Organization Mentions (e.g., UP Police, BJP).
- Person Names Mentions.
- Language Distribution (Hinglish, English, Hindi).

### Keyword & Hashtag Analysis
- Word clouds for top keywords and hashtags.
- Top 10 most-used words and hashtags.
- Engagement breakdown: Likes, Views, Retweets, Replies, Bookmarks, Quotes.

### Heatmap
- Frequency of posts by hour and date (heatmap grid view).

### Geospatial Distribution (Map)
- Interactive map of Uttar Pradesh showing incident density by district.
- Filter by: Date Range, District, Sub-Category.

### KPI Metrics
- District-wise Average Reply Time.
- First Response Time tracking.
- Percentage of posts read.
- Top 10 performing districts.
- Open / Closed / Verified / In-Progress ticket counts.
- District Ticket Resolution Efficiency: Average Open Time, Average Close Time.

### District Internal Report
- Form for District users to submit: FIR details, Religion, Caste, Accused Summary, Incident Description back to HQ.

**Hindi/Hinglish Query Variants:**
- "sentiment analysis kya hai"
- "emotion analysis kahan hoti hai"
- "trend report ka URL kya hai"
- "district performance kaise dekhein"
- "KPI metrics kya hai"
- "map par incidents kaise dekhein"
- "district report kaise banaen"
- "heatmap kahan hai"
- "post engagement kaise dekhein"

---

## Module 12: Platform-Specific Monitoring (Platform Wise Monitoring)

**Concept:** MATRIX monitors the following platforms. Each has dedicated tracking settings and dashboards.

| Platform | What is Monitored | URL |
|---|---|---|
| **X (Twitter)** | Tweets, Retweets, Mentions, Hashtags | `https://matrixupp.com/sc/twitterReporitng` |
| **Facebook** | Posts mentioning @UPPolice on public pages | `https://matrixupp.com/sc/facebookDashboard` |
| **Instagram** | Posts based on tracked hashtags (fetched hourly) | `https://matrixupp.com/sc/instagramLiveSearch` |
| **WhatsApp** | Posts from official media WhatsApp groups joined by HQ number | `https://matrixupp.com/sc/whatsapp` |
| **YouTube** | Posts based on pre-defined keywords for UP districts | Integrated via main dashboard |
| **Web News** | UP-related news from news websites using keywords | `https://matrixupp.com/sc/googleNews` |
| **RSS Feeds** | News from major news website RSS links (polled continuously) | `https://matrixupp.com/sc/rssfeed` |
| **Google News** | Tracking specific keywords (e.g., "UP police") in Google News | `https://matrixupp.com/sc/googleNews` |
| **Google Alerts** | Tracking keywords as Google Alerts | `https://matrixupp.com/sc/googleAlert` |
| **Instagram Hashtags** | Adding/managing tracked hashtags | `https://matrixupp.com/sc/instaHashtag` |
| **Twitter Replies** | Replies to official UP Police tweets | `https://matrixupp.com/sc/twitter-replies-report` |

**Hindi/Hinglish Query Variants:**
- "facebook monitoring kaise hoti hai"
- "instagram hashtag kaise add karein"
- "whatsapp data kahan aata hai"
- "google news kaise track karein"
- "rss feed kaise manage karein"
- "youtube monitoring ka URL kya hai"

---

## Module 13: Suspicious Account & Bot Detection (Fake / Bot Account Pakadna)

**Concept:** MATRIX automatically analyzes accounts to detect bots and fake/suspicious accounts using machine learning and behavioral analysis.

**URL:** `https://matrixupp.com/sc/SuspiciousAccount`

**Detection Criteria (Bot Account Ke Lakshan):**
- **Account Age** — Very new accounts with high activity.
- **Post Frequency** — Posting too fast (too many posts in a short time).
- **Bio Pattern** — Random, meaningless, or absent bio.
- **Username Pattern** — Random letters/numbers in username.
- **Follower/Following Ratio** — Very low followers but follows many accounts.
- **Profile Photo** — Missing or default profile picture.
- **Post Content Pattern** — Repetitive, copy-pasted, or automated content.
- **Suspicious Score** — System-generated score (e.g., Risk 3/5) indicating likelihood of being a bot.

**Result Table Columns:**
- Username, Account Bio, Profile info, Posting Pattern, Risk Score, Follower Stats, Joining Date.

**Hindi/Hinglish Query Variants:**
- "fake account kaise pakdein"
- "bot account detection kya hai"
- "suspicious account ka URL kya hai"
- "bot account ki pehchaan kaise karein"
- "risk score kya hota hai"
- "fake news faila raha account kaise check karein"

---

## Module 14: Influencer & Network Analysis (Influencer Aur Network)

**Concept:** MATRIX identifies key influencers driving narratives and maps the network of connections between social media users and topics.

**Influencer View URL:** `https://matrixupp.com/sc/influencerViewTopicTable`  
**Non-Influencer (Organic) View URL:** `https://matrixupp.com/sc/nonInfluencerViewTopicTable`  
**Connected Accounts Network URL:** `https://matrixupp.com/sc/connectedAccounts`  
**Profile Analysis URL:** `https://matrixupp.com/sc/profileView`  

**Topic Virality Detection:**
- Real-time activity spike alerts.
- Severity Levels: Flash (highest), Critical, High, Medium.
- Shows "Live Trending" indicators for topics going viral.

**Single User Analysis:**
- Deep-dive into one specific account's activity.
- Visual relationship web showing that user's top connected topics.

**Multi-Node Analysis:**
- Visual network graph connecting multiple related topics and users.
- Filter by District and Category.
- Understand coordinated inauthentic behavior (bot networks).

**Hindi/Hinglish Query Variants:**
- "influencer kaun hai"
- "viral topic kaise detect hota hai"
- "network graph kahan dekhein"
- "ek user ka poora analysis kaise karein"
- "coordinated accounts kaise pakdein"
- "topic viral ho raha hai kaise pata karein"

---

## Module 15: Admin Configuration & System Settings (Admin Settings)

**Concept:** HQ-level administrators manage the system's core configuration from the Admin Utilities section.

**Keywords Management URL:** `https://matrixupp.com/sc/keywords`  
**Alternate Keywords URL:** `https://matrixupp.com/sc/keywords1`  
**Keyword Group URL:** `https://matrixupp.com/sc/groupKeyword`  
**Broad Category Management URL:** `https://matrixupp.com/sc/broadCategory`  
**Sub-Category Management URL:** `https://matrixupp.com/sc/subCategory`  
**Instagram Hashtag Management URL:** `https://matrixupp.com/sc/instaHashtag`  
**RSS Feed Management URL:** `https://matrixupp.com/sc/rssfeed`  
**Google Alert Management URL:** `https://matrixupp.com/sc/googleAlert`  
**User Management URL:** `https://matrixupp.com/sc/User`  
**Alert Critical Configuration URL:** `https://matrixupp.com/sc/alertCritical`  

**Keyword Configuration:**
- Keywords can be added in Hindi, English, and Hinglish.
- Mapped to specific Broad Category and Sub-Category.
- Examples: Crime, Caste, Communal, Hate Speech, Traffic.

**Category Structure:**
- **Broad Category** (High-level): CRIME, GRIEVANCE, TRAFFIC, POSITIVE, COMMUNAL, etc.
- **Sub-Category** (Specific): MURDER, THEFT, LOOT, COMMUNAL HATE SPEECH, FAKE NEWS, etc.

**User Role Management:**
- New user creation requires HQ approval.
- Users assigned Main or Sub roles.

**Hindi/Hinglish Query Variants:**
- "keyword kaise add karein"
- "new category kaise banayein"
- "new user kaise approve karein"
- "alert kaise set karein"
- "admin settings ka URL kya hai"
- "sub-category manage kaise karein"

---

## Module 16: Media Archive (Media Archive / Photos Videos)

**Concept:** MATRIX automatically extracts and archives all images and videos from monitored posts.

**URL:** `https://matrixupp.com/sc/archival`  
**Archive View URL:** `https://matrixupp.com/sc/archival/view`  

**Media Archive Features:**
- Photo/Video gallery from captured posts.
- Bookmark filter for media.
- **Factual Summary** — Auto-generated summary of what is in the media.
- **Fact Check** — Checking against known sources.
- **OCR Transcripts** — Extracting text from images using OCR technology.
- **Video Translation** — Translating vernacular video content.

**Hindi/Hinglish Query Variants:**
- "media archive kya hai"
- "photos videos kahan dekhein"
- "OCR kya karta hai"
- "image se text nikalna"
- "video translate kaise karte hain"
- "fact check kaise karein"

---

## Module 17: Complete URL Quick Reference (Saare URLs Ek Jagah)

| Feature | URL |
|---|---|
| **Main Login / DGP Dashboard** | `https://matrixupp.com/sc/dgpDashboard_2` |
| **Standard Dashboard** | `https://matrixupp.com/sc/dashboard` |
| **All Posts Table** | `https://matrixupp.com/sc/allPostTable` |
| **All Topics** | `https://matrixupp.com/sc/allTopics` |
| **All Topics (DGP)** | `https://matrixupp.com/sc/allTopicsDgp` |
| **Ticket Dashboard** | `https://matrixupp.com/sc/ticketDashboard3` |
| **Assigned Tickets** | `https://matrixupp.com/sc/showAllTickets` |
| **In-Progress Tickets** | `https://matrixupp.com/sc/showAllprogressTickets` |
| **Closed Tickets** | `https://matrixupp.com/sc/ticketClosedAndVerification` |
| **Verified Tickets** | `https://matrixupp.com/sc/verifiedTicket` |
| **False Closure Tickets** | `https://matrixupp.com/sc/falseClosureTicket` |
| **Discarded Tickets** | `https://matrixupp.com/sc/showDiscardTicket` |
| **Transfer Post** | `https://matrixupp.com/sc/transfer-post` |
| **Bookmark** | `https://matrixupp.com/sc/bookmark` |
| **Add Reply** | `https://matrixupp.com/sc/addReply` |
| **Reply Category** | `https://matrixupp.com/sc/replyCategory` |
| **Reaction Tracking** | `https://matrixupp.com/sc/reaction` |
| **Twitter Monitoring** | `https://matrixupp.com/sc/twitterReporitng` |
| **Twitter Replies Report** | `https://matrixupp.com/sc/twitter-replies-report` |
| **Facebook Dashboard** | `https://matrixupp.com/sc/facebookDashboard` |
| **WhatsApp** | `https://matrixupp.com/sc/whatsapp` |
| **Instagram Live Search** | `https://matrixupp.com/sc/instagramLiveSearch` |
| **Instagram Hashtag Mgmt** | `https://matrixupp.com/sc/instaHashtag` |
| **Google News** | `https://matrixupp.com/sc/googleNews` |
| **Google Alert** | `https://matrixupp.com/sc/googleAlert` |
| **RSS Feed** | `https://matrixupp.com/sc/rssfeed` |
| **Suspicious Accounts** | `https://matrixupp.com/sc/SuspiciousAccount` |
| **Influencer Topic View** | `https://matrixupp.com/sc/influencerViewTopicTable` |
| **Non-Influencer View** | `https://matrixupp.com/sc/nonInfluencerViewTopicTable` |
| **Pinned Topics** | `https://matrixupp.com/sc/pinnedTopicView` |
| **Profile View** | `https://matrixupp.com/sc/profileView` |
| **Post Monitoring Profiles** | `https://matrixupp.com/sc/postMonitoringProfiles` |
| **Tag Monitoring Profiles** | `https://matrixupp.com/sc/tagMonitoringProfiles` |
| **Connected Accounts** | `https://matrixupp.com/sc/connectedAccounts` |
| **Sentiment Analysis** | `https://matrixupp.com/sc/sentimentAnalysisDashboard` |
| **Monitoring Analysis** | `https://matrixupp.com/sc/monitoringAnalayis` |
| **Trend Report** | `https://matrixupp.com/sc/trendReportOneView` |
| **KPI Metrics** | `https://matrixupp.com/sc/kpimatrixDaskborad` |
| **District Internal Report** | `https://matrixupp.com/sc/districtInternalReportView` |
| **Common Feature Report** | `https://matrixupp.com/sc/commonFeatureReport` |
| **Post Report** | `https://matrixupp.com/sc/postReport` |
| **Newspaper Cutting** | `https://matrixupp.com/sc/newsPaperCuttingPage` |
| **Map / Geospatial** | `https://matrixupp.com/sc/map` |
| **Keywords** | `https://matrixupp.com/sc/keywords` |
| **Keywords (Alt)** | `https://matrixupp.com/sc/keywords1` |
| **Keyword Groups** | `https://matrixupp.com/sc/groupKeyword` |
| **Broad Category** | `https://matrixupp.com/sc/broadCategory` |
| **Sub Category** | `https://matrixupp.com/sc/subCategory` |
| **Media Archive** | `https://matrixupp.com/sc/archival` |
| **Archive View** | `https://matrixupp.com/sc/archival/view` |
| **User Management** | `https://matrixupp.com/sc/User` |
| **Edit Profile** | `https://matrixupp.com/sc/editProfile` |
| **Reset Password** | `https://matrixupp.com/sc/resetPassword` |
| **Active Sessions** | `https://matrixupp.com/sc/active_session` |
| **Login History** | `https://matrixupp.com/sc/login_history` |
| **Alert Critical** | `https://matrixupp.com/sc/alertCritical` |
