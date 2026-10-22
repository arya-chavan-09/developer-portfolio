"""All portfolio content lives here. Edit it, delete the data/ folder,
and restart: the database is re-seeded from this file."""

PROFILE = {
    "name": "Arya Chavan",
    "title": "Backend Developer (.NET & Python)",
    "location": "Mumbai, India",
    "email": "aryachavan09@gmail.com",
    "github": "https://github.com/arya-chavan-09",
    "linkedin": "https://www.linkedin.com/in/arya-chavan-75b752243/",
    "bio": (
        "Software engineer with 2+ years of experience building enterprise web "
        "applications and RESTful APIs with C#, ASP.NET Core and SQL Server. "
        "I design scalable backend services, optimize database performance, and "
        "build microservices using solid object-oriented design. Currently "
        "pursuing a B.S. in Programming and Data Science at IIT Madras, with "
        "hands-on work in machine learning, generative AI and RAG."
    ),
    "open_to_work": True,
}

PROJECTS = [
    {
        "slug": "legal-assistant-rag",
        "title": "Legal Assistant (RAG Application)",
        "summary": "AI-powered legal assistant that answers questions over Bharatiya Nyaya Sanhita (BNS) documents using Retrieval-Augmented Generation.",
        "stack": "Python, FastAPI, LangChain, Ollama, ChromaDB, Vue.js",
        "year": 2025,
        "status": "personal",
        "repo": "https://github.com/arya-chavan-09/legal-assistant",
        "highlights": [
            "PDF ingestion, chunking, embedding generation and semantic retrieval pipeline",
            "Context-aware, conversational question-answering workflow",
            "REST APIs for legal document search and Q&A",
            "Improved answer relevance with metadata-aware retrieval and tuned chunking strategies",
        ],
    },
    {
        "slug": "consumer-behaviour-ml",
        "title": "Consumer Behaviour Analysis using ML",
        "summary": "Machine learning study of consumer behaviour, published and presented at a national conference.",
        "stack": "Python, Scikit-learn, Pandas, NumPy",
        "year": 2024,
        "status": "published",
        "repo": "https://github.com/arya-chavan-09/marketing-strategy",
        "highlights": [
            "Data preprocessing and feature engineering on consumer datasets",
            "Trained and evaluated multiple machine learning models",
            "Generated insights from model results",
            "Research published and presented at a national conference",
        ],
    },
    {
        "slug": "developer-portfolio",
        "title": "Developer Portfolio (this site)",
        "summary": "Portfolio where the terminal is the front end of a real API: every command is an HTTP request.",
        "stack": "Python, FastAPI, SQLite, JavaScript, Docker",
        "year": 2026,
        "status": "live",
        "repo": "https://github.com/arya-chavan-09/developer-portfolio",
        "highlights": [
            "Rate-limited REST API with request telemetry and OpenAPI docs",
            "Read-only SQL endpoint secured with a SQLite authorizer",
            "Token-protected admin commands to manage experience",
            "Automated tests and a Docker image with CI",
        ],
    },
]

SKILLS = [
    {"name": "C#", "category": "language", "level": 5},
    {"name": "Python", "category": "language", "level": 4},
    {"name": "SQL", "category": "language", "level": 5},
    {"name": "JavaScript", "category": "language", "level": 3},
    {"name": "ASP.NET Core", "category": "framework", "level": 5},
    {"name": "ASP.NET MVC", "category": "framework", "level": 5},
    {"name": "Entity Framework Core", "category": "framework", "level": 4},
    {"name": "FastAPI", "category": "framework", "level": 3},
    {"name": "LangChain", "category": "framework", "level": 3},
    {"name": "SQL Server", "category": "database", "level": 5},
    {"name": "Query Optimization", "category": "database", "level": 4},
    {"name": "ChromaDB", "category": "database", "level": 3},
    {"name": "REST API design", "category": "practice", "level": 5},
    {"name": "Microservices", "category": "practice", "level": 4},
    {"name": "OOP & SOLID", "category": "practice", "level": 4},
    {"name": "Azure Entra ID", "category": "cloud", "level": 4},
    {"name": "RAG & LLMs", "category": "ai", "level": 3},
    {"name": "Machine Learning", "category": "ai", "level": 3},
    {"name": "Git", "category": "tools", "level": 4},
    {"name": "Postman", "category": "tools", "level": 4},
]

EXPERIENCE = [
    {
        "company": "Acty Systems India Pvt. Ltd.",
        "role": "Senior Programmer (.NET Developer)",
        "start": "2023-06",
        "end": "2025-08",
        "summary": (
            "Built enterprise web apps with ASP.NET Core MVC and Entity Framework Core, "
            "plus RESTful APIs for business-critical systems. Cut SQL Server response "
            "times by 30% by optimizing queries and stored procedures. Implemented Azure "
            "Entra ID authentication with role-based access control. Worked in Agile "
            "teams: code reviews, debugging and deployments."
        ),
    },
]