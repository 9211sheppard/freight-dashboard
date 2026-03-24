// ─────────────────────────────────────────────────────────────────────────────
//  QUOTES & LEARNING DATA  —  5 books, verified quotes + lessons + quizzes
// ─────────────────────────────────────────────────────────────────────────────

const BOOKS = {
  atomic: {
    id: 'atomic',
    title: 'Atomic Habits',
    author: 'James Clear',
    color: '#e67e22',
    icon: '⚛️',
    quotes: [
      "You do not rise to the level of your goals. You fall to the level of your systems.",
      "Every action you take is a vote for the type of person you wish to become.",
      "Habits are the compound interest of self-improvement.",
      "The most effective form of learning is practice, not planning.",
      "Success is the product of daily habits — not once-in-a-lifetime transformations.",
      "You don't have to be the victim of your environment. You can also be the architect of it.",
      "The purpose of setting goals is to win the game. The purpose of building systems is to continue playing the game.",
      "Getting 1% better every day counts for a lot in the long run.",
      "Make it obvious. Make it attractive. Make it easy. Make it satisfying.",
      "The first mistake is never the one that ruins you. It is the spiral of repeated mistakes that follows.",
    ],
    lessons: [
      {
        title: "The 1% Rule",
        body: "If you get 1% better each day for one year, you'll end up 37 times better by the end. Habits are the compound interest of self-improvement. Small changes feel insignificant at first but deliver remarkable results over years.",
        keyPoint: "Tiny improvements accumulate into extraordinary results over time.",
        quiz: {
          q: "If you improve 1% every day for a year, how many times better will you be?",
          options: ["10x", "20x", "37x", "100x"],
          answer: 2,
          explanation: "1.01^365 = 37.78 — the math of compound growth applied to habits."
        }
      },
      {
        title: "The Four Laws of Behaviour Change",
        body: "James Clear distills habit formation into four laws: (1) Make it Obvious — design your environment so cues are visible. (2) Make it Attractive — pair habits with things you enjoy. (3) Make it Easy — reduce friction, start with 2-minute habits. (4) Make it Satisfying — reward yourself immediately.",
        keyPoint: "To build a habit: obvious, attractive, easy, satisfying. To break one: reverse all four.",
        quiz: {
          q: "Which of the Four Laws focuses on reducing friction to make starting easier?",
          options: ["Make it Obvious", "Make it Attractive", "Make it Easy", "Make it Satisfying"],
          answer: 2,
          explanation: "Make it Easy — reducing friction is the key to lowering the activation energy needed to start."
        }
      },
      {
        title: "Identity-Based Habits",
        body: "Most people focus on outcomes ('I want to lose 20 pounds'). Clear argues you should focus on identity ('I am a healthy person'). Every action is a vote for the person you want to become. Your habits shape your identity, and your identity shapes your habits.",
        keyPoint: "The most lasting habit change comes from changing your identity, not just your outcomes.",
        quiz: {
          q: "According to James Clear, what is the most effective level to focus habit change on?",
          options: ["Outcomes (what you want)", "Processes (what you do)", "Identity (who you are)", "Environment (where you are)"],
          answer: 2,
          explanation: "Identity-based habits are the most durable because they change who you believe you are."
        }
      },
    ]
  },

  power: {
    id: 'power',
    title: 'The Power of Habit',
    author: 'Charles Duhigg',
    color: '#8e44ad',
    icon: '🔄',
    quotes: [
      "Champions don't do extraordinary things. They do ordinary things, but they do them without thinking, too fast for the other team to react.",
      "Change might not be fast and it isn't always easy. But with time and effort, almost any habit can be reshaped.",
      "The Golden Rule of Habit Change: You can't extinguish a bad habit, you can only change it.",
      "If you believe you can change — if you make it a habit — the change becomes real.",
      "Habits are powerful, but delicate. They can emerge outside our consciousness, or can be deliberately designed.",
      "This is the real power of habit: the insight that your habits are what you choose them to be.",
      "Once you understand that habits can change, you have the freedom and the responsibility to remake them.",
      "Small wins are a steady application of a small advantage.",
      "Willpower is the most important keystone habit there is.",
      "Cravings are what drive habits. And figuring out how to spark a craving makes creating a new habit easier.",
    ],
    lessons: [
      {
        title: "The Habit Loop",
        body: "Every habit follows a three-step loop: Cue → Routine → Reward. The cue triggers the brain to go into automatic mode. The routine is the behaviour itself. The reward tells the brain whether this loop is worth remembering. Over time, this loop becomes more and more automatic.",
        keyPoint: "Cue → Routine → Reward. Identify all three to understand and change any habit.",
        quiz: {
          q: "What are the three parts of the Habit Loop in order?",
          options: ["Goal → Action → Result", "Cue → Routine → Reward", "Trigger → Behaviour → Consequence", "Desire → Effort → Satisfaction"],
          answer: 1,
          explanation: "Duhigg's Habit Loop is: Cue (trigger) → Routine (behaviour) → Reward (benefit received)."
        }
      },
      {
        title: "The Golden Rule of Habit Change",
        body: "You cannot extinguish a bad habit — you can only change it. Keep the same cue and the same reward, but insert a new routine. Alcoholics Anonymous works because it replaces the drinking routine with meetings while keeping the cue (stress) and reward (community, relief) the same.",
        keyPoint: "Keep the cue and reward. Change only the routine between them.",
        quiz: {
          q: "According to Duhigg, what is the key to changing a bad habit?",
          options: ["Eliminate the cue", "Replace the routine, keep cue and reward", "Remove the reward", "Ignore the habit entirely"],
          answer: 1,
          explanation: "The Golden Rule: use the same cue and reward, but swap in a new routine."
        }
      },
      {
        title: "Keystone Habits",
        body: "Some habits matter more than others. Keystone habits create a cascade of other good habits. Exercise is a keystone habit — people who start exercising regularly also start eating better, sleeping more, and procrastinating less. Identify and focus on keystone habits for maximum impact.",
        keyPoint: "Focus on keystone habits — one change that automatically triggers many others.",
        quiz: {
          q: "What makes a habit a 'keystone' habit?",
          options: ["It is the hardest habit to form", "It triggers other positive habits", "It only requires willpower", "It produces immediate results"],
          answer: 1,
          explanation: "Keystone habits create a cascade effect, making other positive changes easier."
        }
      },
    ]
  },

  seven: {
    id: 'seven',
    title: 'The 7 Habits of Highly Effective People',
    author: 'Stephen R. Covey',
    color: '#2980b9',
    icon: '7️⃣',
    quotes: [
      "The key is not to prioritize what's on your schedule, but to schedule your priorities.",
      "Most people do not listen with the intent to understand; they listen with the intent to reply.",
      "Begin with the end in mind.",
      "Be proactive.",
      "Put first things first.",
      "Think win-win.",
      "Seek first to understand, then to be understood.",
      "Synergize.",
      "Sharpen the saw.",
      "We see the world, not as it is, but as we are — or, as we are conditioned to see it.",
      "Between stimulus and response there is a space. In that space is our power to choose our response.",
      "Trust is the glue of life. It's the most essential ingredient in effective communication.",
    ],
    lessons: [
      {
        title: "Be Proactive (Habit 1)",
        body: "Proactive people focus their energy on things within their Circle of Influence — what they can control. Reactive people focus on their Circle of Concern — things they can't control (weather, economy, others' behaviour). Expanding your Circle of Influence starts with taking responsibility for your own responses.",
        keyPoint: "Focus on what you can control. Let go of what you can't.",
        quiz: {
          q: "What is the key difference between proactive and reactive people?",
          options: ["Proactive people work harder", "Proactive people focus on what they can control", "Proactive people plan more", "Proactive people are more optimistic"],
          answer: 1,
          explanation: "Proactive people focus on their Circle of Influence (what they control), not their Circle of Concern."
        }
      },
      {
        title: "Seek First to Understand (Habit 5)",
        body: "Most people listen with the intent to reply, not to understand. Empathic listening means listening with your eyes, ears, and heart — understanding someone's frame of reference before trying to be understood. In business, this is the single most important habit for building trust and closing deals.",
        keyPoint: "Listen to understand first. Speak to be understood second.",
        quiz: {
          q: "What does Covey mean by 'empathic listening'?",
          options: ["Feeling sorry for others", "Listening to reply quickly", "Listening to understand the other person's frame of reference", "Agreeing with everything"],
          answer: 2,
          explanation: "Empathic listening means understanding the other person's perspective before formulating your response."
        }
      },
      {
        title: "Think Win-Win (Habit 4)",
        body: "Win-Win is a frame of mind that constantly seeks mutual benefit in all human interactions. It's not your way or my way — it's a better way. In freight and logistics, win-win thinking with agents builds long-term partnerships rather than one-time transactions.",
        keyPoint: "Always seek solutions where both sides benefit. Long-term relationships beat short-term wins.",
        quiz: {
          q: "What is the core belief behind 'Think Win-Win'?",
          options: ["Competition always produces the best results", "Life is a zero-sum game", "There is enough for everyone and mutual benefit is always possible", "Compromise means everyone loses a little"],
          answer: 2,
          explanation: "Win-Win is based on the belief that abundance exists and solutions can benefit all parties."
        }
      },
    ]
  },

  friends: {
    id: 'friends',
    title: 'How to Win Friends and Influence People',
    author: 'Dale Carnegie',
    color: '#27ae60',
    icon: '🤝',
    quotes: [
      "You can make more friends in two months by becoming interested in other people than you can in two years by trying to get other people interested in you.",
      "A person's name is to that person, the sweetest, most important sound in any language.",
      "The only way to get the best of an argument is to avoid it.",
      "Talk to someone about themselves and they'll listen for hours.",
      "When dealing with people, remember you are not dealing with creatures of logic, but creatures of emotion.",
      "Be hearty in your approbation and lavish in your praise.",
      "To be interesting, be interested.",
      "Give the other person a fine reputation to live up to.",
      "The deepest principle in human nature is the craving to be appreciated.",
      "Any fool can criticize, condemn, and complain — and most fools do. But it takes character and self-control to be understanding and forgiving.",
    ],
    lessons: [
      {
        title: "The Power of Genuine Interest",
        body: "Carnegie's most fundamental principle: become genuinely interested in other people. In freight sales and agent relationships, the agents who feel truly heard and valued become your most loyal partners. Ask about their business, their challenges, their market — and actually listen.",
        keyPoint: "Genuine interest in others creates deeper relationships than any sales pitch ever will.",
        quiz: {
          q: "How long does it take to make more friends by being interested in others vs. trying to impress them?",
          options: ["The same time", "2 years vs 2 months (impressing wins)", "2 months vs 2 years (interest wins)", "It doesn't matter"],
          answer: 2,
          explanation: "Carnegie says 2 months of genuine interest outperforms 2 years of trying to get others interested in you."
        }
      },
      {
        title: "Remember Names",
        body: "A person's name is the sweetest sound they know. In business, remembering a contact's name — and using it — instantly differentiates you. It signals that they matter. In your contacts dashboard, you have names — use them in every email, every call, every WhatsApp message.",
        keyPoint: "Use people's names. It's the simplest and most powerful form of respect.",
        quiz: {
          q: "According to Carnegie, what is 'the sweetest, most important sound' to any person?",
          options: ["A sincere compliment", "Their own name", "The sound of agreement", "A thank you"],
          answer: 1,
          explanation: "Carnegie identifies a person's name as the sweetest sound in any language to that person."
        }
      },
      {
        title: "Never Argue — Find Agreement",
        body: "The only way to win an argument is to avoid it. Even if you win logically, you lose emotionally — the other person resents you. In agent disputes or client complaints, find common ground first. Say 'You're right that this is frustrating' before presenting your solution.",
        keyPoint: "You can't win an argument and keep a relationship. Find agreement instead.",
        quiz: {
          q: "What is Carnegie's advice when you find yourself in an argument?",
          options: ["Present your facts clearly", "Win quickly and move on", "Avoid the argument entirely", "Let the other person win"],
          answer: 2,
          explanation: "Carnegie says the best way to win an argument is to avoid it — winning logically often means losing the relationship."
        }
      },
    ]
  },

  think: {
    id: 'think',
    title: 'Think and Grow Rich',
    author: 'Napoleon Hill',
    color: '#c0392b',
    icon: '💡',
    quotes: [
      "Whatever the mind of man can conceive and believe, it can achieve.",
      "A goal is a dream with a deadline.",
      "The starting point of all achievement is desire.",
      "You are the master of your destiny. You can influence, direct and control your own environment.",
      "Strength and growth come only through continuous effort and struggle.",
      "The secret of getting ahead is getting started.",
      "Set your mind on a definite goal and observe how quickly the world stands aside to let you pass.",
      "Every adversity, every failure, every heartache carries with it the seed of an equal or greater benefit.",
      "Your big opportunity may be right where you are now.",
      "No more effort is required to aim high in life, to demand abundance and prosperity, than is required to accept misery and poverty.",
      "Patience, persistence and perspiration make an unbeatable combination for success.",
    ],
    lessons: [
      {
        title: "The Power of Definite Purpose",
        body: "Hill's first principle: you must know exactly what you want and be obsessed with getting it. Vague desires produce vague results. Write down your goal, the exact amount of money you intend to make, the deadline, and what you will give in return. Read it aloud twice a day.",
        keyPoint: "A burning desire backed by a definite plan is the starting point of all achievement.",
        quiz: {
          q: "What does Napoleon Hill identify as the starting point of all achievement?",
          options: ["Intelligence", "Education", "Desire", "Opportunity"],
          answer: 2,
          explanation: "Hill says 'The starting point of all achievement is desire' — not talent, luck, or education."
        }
      },
      {
        title: "The Mastermind Principle",
        body: "No individual has ever achieved great success alone. The Mastermind is the coordination of knowledge and effort between two or more people toward a definite purpose. Your network of agents worldwide IS your mastermind group — each one brings local knowledge, connections and expertise you don't have.",
        keyPoint: "Surround yourself with people whose skills complement yours. That network is your greatest asset.",
        quiz: {
          q: "What does Hill call the principle of two or more minds working together toward a common goal?",
          options: ["Teamwork", "The Mastermind", "Synergy", "Collaboration"],
          answer: 1,
          explanation: "Hill calls it the Mastermind Principle — coordinated effort between aligned minds creates power beyond the sum of parts."
        }
      },
      {
        title: "Turning Failure Into Success",
        body: "Every adversity carries the seed of an equal or greater benefit. Hill studied 500 of the most successful people in history and found they all experienced major failure before their greatest success. Edison failed 10,000 times before the lightbulb. The difference: they refused to call it failure — they called it learning.",
        keyPoint: "Every failure contains the seeds of your next success — if you look for them.",
        quiz: {
          q: "How did Thomas Edison reportedly describe his 10,000 failed attempts at the lightbulb?",
          options: ["Costly mistakes", "10,000 ways that didn't work", "Unnecessary experiments", "Wasted time"],
          answer: 1,
          explanation: "Edison said 'I have not failed. I've just found 10,000 ways that won't work.' — the mindset Hill teaches."
        }
      },
    ]
  },
  ai: {
    id: 'ai',
    title: 'AI Tools Masterclass',
    author: 'Live Knowledge — 2025/2026',
    color: '#00b4d8',
    icon: '🤖',
    quotes: [
      "Humans with AI will replace humans without AI.",
      "ChatGPT does in 10 seconds what used to take an hour. The question is: are you using it?",
      "Perplexity doesn't just search — it thinks, cites, and answers. Google hasn't been this disrupted in 20 years.",
      "Claude Code doesn't just write code — it reads your whole project, understands context, and builds features end to end.",
      "The best AI tool is the one you actually use every day.",
      "AI is not a destination. It is a moving target — and it's moving fast.",
      "Every professional who ignores AI today is falling behind someone who uses it.",
      "The gap between AI users and non-users is doubling every six months.",
      "You don't need to understand how a plane's engine works to fly first class.",
      "AI is the most powerful productivity tool ever created. Most people use 2% of it.",
    ],
    lessons: [
      {
        title: "ChatGPT — What It Can Actually Do",
        body: "ChatGPT (by OpenAI) is the most widely used AI assistant in the world. Real uses right now: Write and edit professional emails in any language in seconds. Summarise long documents, contracts, or PDFs instantly. Draft freight quotations, proposals, and cover letters. Research any company or market in minutes. Translate messages with cultural context — not just word-for-word. Prepare for client meetings by asking ChatGPT to brief you on the company. GPT-4o (the latest model) also reads images — photograph a handwritten document and it will type it out.",
        keyPoint: "ChatGPT is your 24/7 writing partner, researcher, translator, and advisor — all in one.",
        quiz: {
          q: "Which of these can ChatGPT NOT reliably do in 2025?",
          options: ["Write a professional email", "Translate a document with cultural nuance", "Browse the live internet in real time for free", "Summarise a long PDF"],
          answer: 2,
          explanation: "Free ChatGPT does not browse the live internet — that requires a paid plan with browsing enabled. Claude and Perplexity have better real-time web access."
        }
      },
      {
        title: "Claude — The AI Built for Deep Work",
        body: "Claude (by Anthropic — the same AI powering this dashboard) is designed for longer, more complex tasks. Where Claude excels: Reading and analysing very long documents (entire contracts, reports, books). Writing with a more natural, nuanced tone than ChatGPT. Coding assistance — Claude can read your entire codebase and write working features. Following complex multi-step instructions without losing context. Claude is especially trusted in professional settings because it refuses harmful requests and cites its reasoning. Claude Code (the tool used to build this dashboard) can autonomously build entire software projects.",
        keyPoint: "Claude is the go-to AI for long documents, complex reasoning, and building software — it thinks before it speaks.",
        quiz: {
          q: "What makes Claude particularly strong compared to other AI assistants?",
          options: ["It has the most users", "It handles very long documents and complex multi-step tasks exceptionally well", "It is completely free", "It can make phone calls"],
          answer: 1,
          explanation: "Claude's key strength is its large context window and ability to follow complex, multi-step instructions across long documents — ideal for professional and technical work."
        }
      },
      {
        title: "Perplexity — The Google Killer",
        body: "Perplexity AI is a search engine powered by AI. Unlike Google, it reads the web and gives you a direct answer with cited sources — no ads, no link clicking required. Use it for: Instant market research on any company or country. Finding current freight rates and shipping news. Checking if an agent company is legitimate. Researching competitors. Getting summarised news on any topic. The Pro version ($20/month) searches deeper and uses multiple AI models. For business research, Perplexity is faster and more accurate than any traditional search engine.",
        keyPoint: "Perplexity replaces hours of Google research with a direct, cited answer in 10 seconds.",
        quiz: {
          q: "What is the key advantage of Perplexity over traditional Google search?",
          options: ["It has more results", "It gives a direct AI-generated answer with cited sources — no ads, no clicking", "It is faster to load", "It has better images"],
          answer: 1,
          explanation: "Perplexity reads the web and synthesises a direct answer with citations — no ads, no sifting through 10 blue links. It fundamentally changes how you research."
        }
      },
      {
        title: "Claude Code — AI That Builds Software",
        body: "Claude Code is the AI tool that literally built this dashboard you are using right now. It is a command-line tool that sits inside your project folder and can: Read every file in your codebase simultaneously. Write new features, fix bugs, and refactor code. Run tests and terminal commands. Build complete apps from scratch based on your description. This is not autocomplete — it is an AI that understands your entire project and acts like a senior developer. Non-programmers can now describe what they want in plain English and have a working app built in hours.",
        keyPoint: "Claude Code built this entire dashboard. Non-programmers can now build real software by describing what they want.",
        quiz: {
          q: "What makes Claude Code different from a regular AI chatbot?",
          options: ["It only works with Python", "It reads your entire codebase and acts autonomously as a developer", "It requires a computer science degree", "It only fixes bugs"],
          answer: 1,
          explanation: "Claude Code reads all your project files simultaneously, understands the full context, and can autonomously build, fix, and deploy features — it's a full AI developer, not just a chatbot."
        }
      },
      {
        title: "Zapier & Make — Automation Without Code",
        body: "Zapier and Make (formerly Integromat) connect your apps and automate repetitive tasks without any coding. Examples you can build today: When a new email arrives with 'quotation' in the subject, automatically add it to a spreadsheet. When someone fills a contact form, auto-send a WhatsApp message. When you add a new contact to your dashboard, auto-create a task in your to-do app. Zapier has 6,000+ app connections. Most automations take 10 minutes to set up. Cost: Free tier covers most small business needs. Combined with AI, you can build workflows that read emails, extract data, and update spreadsheets — all automatically.",
        keyPoint: "Zapier + AI = a personal assistant that works 24/7, never takes a break, and costs less than a coffee per day.",
        quiz: {
          q: "What is the main purpose of tools like Zapier and Make?",
          options: ["Writing code from scratch", "Connecting apps and automating repetitive tasks without coding", "Replacing human decision-making", "Managing social media only"],
          answer: 1,
          explanation: "Zapier and Make automate workflows between apps — no coding required. They are the bridge that connects your tools and eliminates repetitive manual tasks."
        }
      },
    ]
  },

  logistics: {
    id: 'logistics',
    title: 'Freight & Logistics Masterclass',
    author: 'Industry Knowledge — Live Trade Data',
    color: '#0077b6',
    icon: '🚢',
    quotes: [
      "Incoterms are not suggestions — they are the contract. Get them wrong and you own the cargo.",
      "FOB means the seller's job ends at the port rail. Everything after that is your problem.",
      "A Bill of Lading is three things at once: a receipt, a contract, and a document of title. Lose it and you lose the cargo.",
      "LCL is not cheaper than FCL — it's slower, riskier, and only economical below 15 CBM.",
      "China → US West Coast: 12–18 days. China → US East Coast via Panama: 25–40 days. Know the difference before you quote.",
      "Prince Rupert is the fastest port into North America from Asia. Most agents don't know it exists.",
      "Jebel Ali is not just a UAE port — it's the transshipment hub for 50+ countries in the region.",
      "Rotterdam handles more cargo than any port in Europe. If you're quoting Europe, start with NLRTM.",
      "The Suez Canal saves 7,000 nautical miles vs. going around Africa. That's why everything goes through it.",
      "HS codes are the passport of your cargo. Wrong code = delay, fine, or seizure.",
      "DDP sounds great for the buyer. It's a nightmare for the freight forwarder who didn't calculate duties correctly.",
      "Transit time is a range, not a promise. Build buffer into every quote you give.",
    ],
    lessons: [
      {
        title: "Incoterms 2020 — The Rules Every Freight Pro Must Know",
        body: `Incoterms (International Commercial Terms) are published by the ICC and define who pays for what in international trade. There are 11 terms — the most critical to know:\n\n<strong>EXW (Ex Works)</strong> — Buyer does everything. Seller just makes goods available at their factory. Maximum risk for buyer.\n\n<strong>FOB (Free On Board)</strong> — Seller delivers to port and loads onto ship. From that moment, buyer's risk and cost. Most common term in Asia-origin shipments.\n\n<strong>CIF (Cost, Insurance, Freight)</strong> — Seller pays freight + insurance to destination port. But risk transfers at origin port. Common in commodity trading.\n\n<strong>DAP (Delivered At Place)</strong> — Seller delivers to named destination, buyer pays import duties. Clean and simple for buyers.\n\n<strong>DDP (Delivered Duty Paid)</strong> — Seller pays everything including import duties. Maximum risk for seller/forwarder. Be very careful quoting DDP without knowing exact duty rates.`,
        keyPoint: "FOB = seller's job ends at the loading port. DDP = seller/forwarder responsible for everything door to door.",
        quiz: {
          q: "Under FOB terms, when does risk transfer from seller to buyer?",
          options: [
            "When goods leave the seller's warehouse",
            "When goods are loaded onto the vessel at the origin port",
            "When goods arrive at the destination port",
            "When the buyer takes physical delivery"
          ],
          answer: 1,
          explanation: "FOB (Free On Board): risk and cost transfer to the buyer the moment goods are loaded onto the vessel at the named origin port."
        }
      },
      {
        title: "FCL vs LCL — Choosing the Right Freight Mode",
        body: `<strong>FCL (Full Container Load)</strong> — You book an entire container (20ft or 40ft). Your cargo, your container, sealed at origin.\n\n✅ Faster · Lower damage risk · Better rates above ~15 CBM · Direct port to port\n\n<strong>LCL (Less than Container Load)</strong> — Your cargo shares a container with other shippers' goods. Consolidated at a CFS (Container Freight Station).\n\n✅ Good for small shipments under 10–12 CBM · More flexible\n❌ Slower (consolidation + deconsolidation adds 3–7 days) · Higher damage risk · More handling\n\n<strong>The Rule of Thumb:</strong>\n- Under 10 CBM → LCL\n- 10–15 CBM → Compare rates\n- Over 15 CBM → FCL almost always wins on cost and speed\n\n<strong>Standard container sizes:</strong>\n- 20ft: ~25–27 CBM / ~21,700 kg\n- 40ft: ~55–58 CBM / ~26,500 kg\n- 40ft HC (High Cube): ~67–68 CBM`,
        keyPoint: "Above 15 CBM, FCL wins on price, speed, and safety. LCL is for small, flexible shipments only.",
        quiz: {
          q: "A client has 18 CBM of cargo. What is usually the better option?",
          options: [
            "LCL — it's cheaper for anything under 20 CBM",
            "FCL — above 15 CBM it's usually faster and cheaper",
            "Air freight — faster than both",
            "It doesn't matter — both are identical above 10 CBM"
          ],
          answer: 1,
          explanation: "At 18 CBM, FCL (20ft container) is almost always the better choice — faster, cheaper per CBM, and lower damage risk than LCL consolidation."
        }
      },
      {
        title: "Core Trade Lanes — Transit Times You Must Know",
        body: `<strong>🇨🇳 China → 🇺🇸 USA (Transpacific — highest volume in the world)</strong>\n- West Coast (USLAX / USLGB): 12–18 days\n- East Coast (USNYC / USSAV) via Panama: 25–40 days\n- Pro tip: Prince Rupert (CAPRR) is 2–4 days faster than Vancouver for Asia cargo heading inland by rail.\n\n<strong>🇮🇳 India → 🇺🇸 USA</strong>\n- Nhava Sheva / Mundra → New York / Savannah / Houston: 22–35 days\n- Often via Suez or Mediterranean transshipment\n\n<strong>🇦🇪 UAE → 🇺🇸 USA</strong>\n- Jebel Ali → New York / Savannah / Houston: 25–40 days\n- Jebel Ali is a relay hub — not origin-heavy but critical for Middle East + East Africa cargo\n\n<strong>🇪🇺 Europe → 🇺🇸 USA (most reliable)</strong>\n- Rotterdam / Antwerp / Hamburg → New York: 10–18 days\n- Mostly direct services with high reliability\n\n<strong>🇨🇳 China → 🇪🇺 Europe</strong>\n- Shanghai / Ningbo → Rotterdam / Antwerp: 25–40 days via Suez Canal\n\n<strong>Strategic logic:</strong>\n- Europe lanes = speed clients\n- India lanes = cost clients\n- UAE = flexibility / overflow routing`,
        keyPoint: "China → US West Coast = 12–18 days. China → US East Coast = 25–40 days. Europe → US = 10–18 days. Know these before quoting.",
        quiz: {
          q: "A client needs cargo from Shanghai to New York urgently. What is the approximate sea transit time?",
          options: [
            "12–18 days (same as West Coast)",
            "25–40 days via Panama Canal",
            "5–8 days (express service)",
            "45–60 days"
          ],
          answer: 1,
          explanation: "Shanghai → New York goes via Panama Canal (East Coast routing) and takes approximately 25–40 days — significantly longer than West Coast ports like LA/Long Beach."
        }
      },
      {
        title: "The Bill of Lading — Your Most Important Document",
        body: `The <strong>Bill of Lading (B/L)</strong> is the single most important document in ocean freight. It serves three functions simultaneously:\n\n<strong>1. Receipt</strong> — proof the carrier received the cargo in the stated condition\n<strong>2. Contract of Carriage</strong> — the legal agreement between shipper and carrier\n<strong>3. Document of Title</strong> — whoever holds the original B/L has the right to claim the cargo\n\n<strong>Types of B/L:</strong>\n- <strong>Original B/L</strong> — physical document; cargo cannot be released without it. High risk if lost.\n- <strong>Sea Waybill (SWB)</strong> — non-negotiable; cargo released to named consignee without original. Faster, lower risk.\n- <strong>Telex Release</strong> — seller surrenders original at origin, buyer notified electronically. No original needed at destination.\n- <strong>Express B/L</strong> — same as telex release, faster processing.\n\n<strong>Key fields every forwarder must check:</strong>\nShipper · Consignee · Notify Party · Port of Loading · Port of Discharge · Description of Goods · Number of Containers · Freight Terms (Prepaid or Collect)`,
        keyPoint: "The B/L is the title to the cargo. Whoever holds it owns it. Always verify every field before issuing.",
        quiz: {
          q: "What is a Telex Release?",
          options: [
            "A type of container used for temperature-sensitive cargo",
            "A method where the original B/L is surrendered at origin, allowing release at destination without a physical original",
            "An express courier service for shipping documents",
            "A fee charged by carriers for documentation"
          ],
          answer: 1,
          explanation: "Telex Release: the shipper surrenders the original B/L at origin; the carrier instructs the destination agent to release cargo to the consignee without requiring the physical original document."
        }
      },
      {
        title: "HS Codes & Customs — Why They Make or Break a Shipment",
        body: `<strong>HS Code (Harmonized System Code)</strong> is a 6–10 digit number that classifies every product traded globally. Every customs authority uses it.\n\n<strong>Why it matters to you:</strong>\n- Determines the import duty rate\n- Triggers inspections for certain product types\n- Wrong code = delay, fine, or seizure\n- Varies by country (first 6 digits are universal; digits 7–10 are country-specific)\n\n<strong>Common freight forwarder mistakes:</strong>\n- Using a "close enough" HS code to reduce duty (fraud — customs agencies have AI now)\n- Not updating codes when product specs change\n- Not checking if the destination country has anti-dumping duties on that code (especially China-origin goods to USA/EU)\n\n<strong>Key customs documents:</strong>\n- Commercial Invoice\n- Packing List\n- Certificate of Origin (CO) — proves where goods were made\n- Bill of Lading\n- Import License (for controlled goods)\n\n<strong>Incoterms + HS Codes combined</strong>: Under DDP terms, the forwarder is liable for correct HS codes AND correct duty payment. A wrong HS code on DDP = your problem, not the client's.`,
        keyPoint: "The HS code determines the duty rate. Wrong code = delay, fine, or seizure. Always verify before quoting DDP.",
        quiz: {
          q: "Who is responsible for correct HS codes and duty payment under DDP (Delivered Duty Paid) terms?",
          options: [
            "The buyer / importer",
            "The customs authority",
            "The seller / freight forwarder who quoted DDP",
            "The shipping line"
          ],
          answer: 2,
          explanation: "Under DDP, the seller (or their freight forwarder) is responsible for everything including correct HS code classification and full duty payment at the destination country."
        }
      },
    ]
  },

  influence: {
    id: 'influence',
    title: 'Influence',
    author: 'Robert Cialdini',
    color: '#e74c3c',
    icon: '🧠',
    quotes: [
      "The most powerful word in the English language may be the one spoken before any request: 'because.'",
      "Give first. The obligation to give back is one of the most deeply embedded instincts in human nature.",
      "People follow the lead of similar others. Show them that people like them are already saying yes.",
      "We trust people we like. Likeability is not a personality trait — it is a skill.",
      "Commitment, once made publicly, creates its own momentum. Get the first yes and the rest follow.",
      "Scarcity makes ordinary things precious. What is rare is valuable — even if it wasn't yesterday.",
    ],
    lessons: [
      {
        title: "Reciprocity",
        body: "Give first, receive later. People feel deeply obligated to return favors — it is one of the most universal rules of human culture. In outreach, offering genuine value before asking creates a psychological debt that makes people want to respond. A useful market insight, a free introduction, or a simple act of generosity primes the relationship.",
        keyPoint: "Those who give first receive more. Reciprocity is not manipulation — it is the foundation of trust.",
        quiz: {
          q: "According to Cialdini, why does giving something of value before making a request increase compliance?",
          options: [
            "It distracts the other person from saying no",
            "It triggers the deeply embedded human drive to reciprocate — people feel obligated to return favors",
            "It makes you appear wealthier and more established",
            "It delays the conversation long enough to build familiarity"
          ],
          answer: 1,
          explanation: "Reciprocity is one of Cialdini's six principles — humans are hardwired to return favors. Giving first creates a sense of obligation that significantly increases the likelihood of a yes."
        }
      },
      {
        title: "Social Proof",
        body: "People follow what others do — especially others who are similar to them. When uncertain, humans look to the crowd for signals of the correct action. Mentioning that other freight agents in the same region already work with Flash Cargo Global creates comfort and reduces resistance. A simple 'We currently work with partners in Brazil, Colombia, and Peru' carries enormous weight.",
        keyPoint: "Show that similar people are already saying yes. Social proof removes uncertainty and reduces the fear of being first.",
        quiz: {
          q: "Which of the following best uses the principle of Social Proof in an outreach email?",
          options: [
            "We are the best freight company in the market",
            "Our rates are lower than any competitor",
            "We currently partner with agents across Southeast Asia who handle similar lanes to yours",
            "Please respond within 48 hours as we have limited availability"
          ],
          answer: 2,
          explanation: "Mentioning similar partners already working with you applies social proof — it shows the prospect that people like them have already made this decision, reducing perceived risk."
        }
      },
      {
        title: "Liking",
        body: "People say yes to people they like. Research shows that likeability is influenced by similarity, compliments, and familiarity — all of which can be engineered in writing. Using the agent's name, referencing their city or country, acknowledging their specific market, and showing genuine curiosity about their business makes you likeable before you ever ask for anything.",
        keyPoint: "Build genuine rapport before making any ask. People do business with people they like, not just companies they need.",
        quiz: {
          q: "Which action best applies the Liking principle in a cold outreach email?",
          options: [
            "Sending the same template to every contact without personalisation",
            "Mentioning your company's revenue and history upfront",
            "Using the agent's name, referencing their city, and expressing genuine interest in their market",
            "Offering a discount in the first email"
          ],
          answer: 2,
          explanation: "Personalisation — using someone's name, referencing their location, and showing interest in their specific situation — triggers the Liking principle and dramatically increases response rates."
        }
      },
      {
        title: "Commitment & Consistency",
        body: "Once someone takes a small action, they are far more likely to keep engaging — because people want to be consistent with their prior choices. Getting a single reply to an intro email is the most important first step. Even a small commitment ('Yes, send me more info') psychologically aligns the agent toward continued engagement. Get the first reply and the rest follows.",
        keyPoint: "Small commitments lead to larger ones. The goal of the first email is not a deal — it is a reply.",
        quiz: {
          q: "Why does Cialdini say getting a small 'yes' early in a conversation matters so much?",
          options: [
            "It locks the other person into a legal agreement",
            "It generates revenue immediately",
            "People feel compelled to remain consistent with their earlier commitments, making larger yeses more likely",
            "It signals that the other person has budget to spend"
          ],
          answer: 2,
          explanation: "Commitment & Consistency: once someone takes a small action, they experience psychological pressure to stay consistent with that choice — making future engagement significantly more likely."
        }
      },
      {
        title: "Authority",
        body: "People trust experts and defer to those who demonstrate credibility and command of their domain. You do not need to boast — you need to signal authority through specifics. Positioning Flash Cargo Global as a global operator with active customers on named lanes, referencing real transit times and port pairs, and speaking with precision all signal expertise without bragging.",
        keyPoint: "Authority is demonstrated through specifics, not claims. Say what you know, not just who you are.",
        quiz: {
          q: "Which statement best demonstrates Authority in a freight outreach context?",
          options: [
            "We are a world-class logistics company with excellent service",
            "We are the best in the industry — you should trust us",
            "We currently move cargo on the China–West Coast US lane with 14-day transit times via Maersk and Hapag-Lloyd",
            "We have many satisfied clients around the world"
          ],
          answer: 2,
          explanation: "Specificity signals expertise. Naming real lanes, carriers, and transit times demonstrates operational authority — something vague claims of 'excellence' never achieve."
        }
      },
      {
        title: "Scarcity",
        body: "People want more of what they can have less of. Scarcity increases perceived value and triggers fear of missing out. In agent partnerships, you can apply this by communicating that you select only a few trusted partners per region — rather than working with everyone. This shifts the dynamic: instead of you asking them for help, they become interested in qualifying for a limited opportunity.",
        keyPoint: "Scarcity creates desire. Positioning your partnership as selective makes agents want to earn it.",
        quiz: {
          q: "How does Cialdini's Scarcity principle apply to building an agent network?",
          options: [
            "Offer discounts that expire in 24 hours to create urgency",
            "Tell agents you only select a limited number of partners per region, making the opportunity feel exclusive",
            "Limit the number of shipments you handle per month",
            "Avoid replying quickly so agents think you are busy"
          ],
          answer: 1,
          explanation: "Communicating that you selectively choose partners per region applies Scarcity — it transforms the dynamic from you seeking agents to agents wanting to qualify for a limited opportunity."
        }
      },
    ]
  },

  neversplit: {
    id: 'neversplit',
    title: 'Never Split the Difference',
    author: 'Chris Voss',
    color: '#8e44ad',
    icon: '🎯',
    quotes: [
      "The most dangerous negotiation is the one you don't know you're in.",
      "No deal is better than a bad deal. Walking away is a power move, not a failure.",
      "Empathy is not about being nice. It's about understanding the other side well enough to influence them.",
      "'No' is not rejection — it is the start of the real conversation.",
      "Bend their reality, don't meet in the middle. Compromise is often just two people being equally unhappy.",
      "The word 'fair' is the most powerful and dangerous word in any negotiation.",
    ],
    lessons: [
      {
        title: "Tactical Empathy",
        body: "Tactical Empathy means understanding the other side's perspective deeply — not to agree with it, but to navigate it. Before making any ask, acknowledge the other person's reality. In email outreach, this means recognising that your contact is busy, receives dozens of emails, and is selective about partners — and saying so. This disarms defensiveness before it forms.",
        keyPoint: "Acknowledge their world before making your ask. Feeling understood makes people open to listening.",
        quiz: {
          q: "What is the goal of Tactical Empathy in a negotiation or outreach context?",
          options: [
            "To agree with everything the other person says",
            "To understand and acknowledge the other side's perspective deeply enough to reduce resistance",
            "To make the other person feel sorry for you",
            "To delay the conversation until the other person lowers their guard"
          ],
          answer: 1,
          explanation: "Tactical Empathy is not about sympathy — it is about deeply understanding the other side's emotional state and perspective, then demonstrating that understanding to build trust and reduce resistance."
        }
      },
      {
        title: "Mirroring",
        body: "Mirroring is repeating the last 2–3 words someone said, in a slightly questioning tone, to encourage them to keep talking. It is the simplest negotiation tool and one of the most effective. In email follow-ups, reference exactly what the other person said in their last reply — it signals that you listened and creates a natural conversational flow that feels effortless to continue.",
        keyPoint: "Repeat the last few words. It costs nothing and signals deep attention — which makes people open up.",
        quiz: {
          q: "In email follow-ups, how does Mirroring apply?",
          options: [
            "Copy the structure of the other person's email template",
            "Reference exactly what the other person said in their previous reply to show you listened",
            "Use the same greeting they used in every email",
            "Send your email at the same time of day they sent theirs"
          ],
          answer: 1,
          explanation: "Mirroring in email means referencing the other person's exact words from their last message — it creates continuity, shows you paid attention, and makes the conversation feel natural rather than transactional."
        }
      },
      {
        title: "Labeling",
        body: "Labeling means naming the emotion you sense the other person is feeling. It validates their position without requiring you to agree with it. In outreach, a label like 'It sounds like you're selective about which partners you work with' does three things: it shows empathy, it flatters their discernment, and it opens dialogue. Labels start with 'It sounds like…' or 'It seems like…' — never 'I think you feel…'",
        keyPoint: "Name the emotion. Feeling understood is the fastest path to opening a dialogue.",
        quiz: {
          q: "Which of the following is a correctly structured Label according to Chris Voss?",
          options: [
            "I think you feel overwhelmed by too many partner requests.",
            "It sounds like you're selective about which networks you join.",
            "You seem like someone who doesn't need new partners right now.",
            "I understand you are busy and probably not interested."
          ],
          answer: 1,
          explanation: "Labels start with 'It sounds like…' or 'It seems like…' — not 'I think you feel.' They name the perceived emotion without projecting or accusing, which validates rather than challenges."
        }
      },
      {
        title: "The No-Oriented Question",
        body: "Voss found that 'no' makes people feel safe — they feel in control and protected. Asking questions that invite a 'no' response dramatically increases reply rates. 'Is now a bad time?' gets far more responses than 'Can we connect?' because the person answering 'no' feels they are correcting you — which is a comfortable, low-risk action. The no opens the door.",
        keyPoint: "Ask for 'no' to get a reply. Safety produces engagement; pressure produces silence.",
        quiz: {
          q: "Why does 'Is now a bad time?' outperform 'Can we connect?' in cold outreach?",
          options: [
            "It is shorter and easier to read",
            "It invites a 'no' response, which makes the recipient feel safe and in control — triggering a reply",
            "It implies urgency, which creates pressure to respond",
            "It suggests you already have an appointment planned"
          ],
          answer: 1,
          explanation: "No-oriented questions give the other person a sense of control — answering 'no' (it's not a bad time) feels safe and protective, dramatically increasing reply rates compared to 'yes' questions that create pressure."
        }
      },
      {
        title: "Calibrated Questions",
        body: "Calibrated Questions use 'how' and 'what' to gather information and invite collaboration without triggering defensiveness. They give the other person the illusion of control while steering the conversation. In freight prospecting: 'What lanes are most important to your business right now?' or 'How do you currently handle your US imports?' are far more powerful than yes/no questions that close down dialogue.",
        keyPoint: "How and what questions invite collaboration. They gather intelligence while making the other person feel heard.",
        quiz: {
          q: "Which of the following is a well-formed Calibrated Question?",
          options: [
            "Do you ship to the US?",
            "Can you handle our cargo?",
            "What lanes are most critical to your business right now?",
            "Are you interested in working with us?"
          ],
          answer: 2,
          explanation: "'What lanes are most critical to your business?' is a calibrated question — it uses 'what', invites a detailed answer, gives the other person control, and gathers exactly the intelligence you need."
        }
      },
      {
        title: "The Late-Night FM DJ Voice",
        body: "Voss identifies three voice types: assertive, playful/accommodating, and the late-night FM DJ voice — slow, calm, deliberate, and warm. The DJ voice signals confidence, trustworthiness, and patience. In written communication, this translates to short sentences, no exclamation marks, no desperation, and a tone that says 'I have time for you.' Calm writing is powerful writing.",
        keyPoint: "Slow, warm, deliberate tone signals confidence. Urgency and excitement in writing signal desperation.",
        quiz: {
          q: "How does the 'Late-Night FM DJ Voice' translate into professional email writing?",
          options: [
            "Use enthusiastic language and exclamation marks to show energy",
            "Write long, detailed emails to demonstrate thoroughness",
            "Use short sentences, a warm tone, no exclamation marks — calm and deliberate like someone who doesn't need to impress",
            "Write in all lowercase to seem casual and approachable"
          ],
          answer: 2,
          explanation: "The DJ Voice in email means calm, unhurried, warm prose — short sentences, no desperation, no exclamation marks. It signals confidence and trustworthiness, not eagerness or pressure."
        }
      },
    ]
  },

};

// Flat list of all quotes for the ticker
const ALL_QUOTES = Object.values(BOOKS).flatMap(book =>
  book.quotes.map(q => ({ text: q, book: book.title, author: book.author, color: book.color }))
);
