"""150-question evaluation suite for the global-search answer pipeline.
Extracted from test_benchmark_ab.py (Phase 0 of the results-gathering plan).
Each entry: (query, access_context, category, expect_answer)."""

from iris.domain.search.lecture_search_dto import AccessContext


def ctx(course_ids: list[int], is_staff: bool = True) -> AccessContext:
    return AccessContext(
        courseIds=course_ids,
        userId=1,
        userLogin="bench",
        editorCourseIds=course_ids if is_staff else [],
        taCourseIds=[],
        studentCourseIds=course_ids,
        staffCourseIds=course_ids if is_staff else [],
        isStaff=is_staff,
    )


CTX_DL = ctx([7])  # Deep Learning (104 segments)
CTX_PSE = ctx([9])  # PSE (8 segments)
CTX_CONC = ctx([10])  # Concurrent Programming (1 video)
CTX_RNN = ctx([11])  # RNN quiz course
ADMIN = None  # no filter — all entities visible

# ─── 150-question suite ───────────────────────────────────────────────────────
# Each entry: (query, access_context, category, expect_answer)
# expect_answer=True  → should produce an answer
# expect_answer=False → should return null (out of scope or catalog)

QUESTIONS: list[tuple[str, AccessContext | None, str, bool]] = [
    # ── Deep Learning: smart / precise (20) ───────────────────────────────────
    (
        "What is the difference between L1 and L2 regularization?",
        CTX_DL,
        "DL/smart",
        True,
    ),
    ("How does dropout prevent overfitting?", CTX_DL, "DL/smart", True),
    (
        "Explain the chain rule in the context of backpropagation",
        CTX_DL,
        "DL/smart",
        True,
    ),
    (
        "What is the difference between batch gradient descent and stochastic gradient descent?",
        CTX_DL,
        "DL/smart",
        True,
    ),
    ("How does the sigmoid activation function saturate?", CTX_DL, "DL/smart", True),
    (
        "What is maximum likelihood estimation and how is it used in logistic regression?",
        CTX_DL,
        "DL/smart",
        True,
    ),
    (
        "What is cross-entropy loss and why is it preferred for classification?",
        CTX_DL,
        "DL/smart",
        True,
    ),
    (
        "Explain the role of the learning rate in gradient descent",
        CTX_DL,
        "DL/smart",
        True,
    ),
    ("What is the bias-variance tradeoff?", CTX_DL, "DL/smart", True),
    (
        "How is logistic regression related to linear regression?",
        CTX_DL,
        "DL/smart",
        True,
    ),
    (
        "What does the weight matrix represent in a neural network layer?",
        CTX_DL,
        "DL/smart",
        True,
    ),
    (
        "Explain mini-batch gradient descent and its advantages over full-batch",
        CTX_DL,
        "DL/smart",
        True,
    ),
    (
        "What is a hyperparameter and how does it differ from a model parameter?",
        CTX_DL,
        "DL/smart",
        True,
    ),
    (
        "How is the softmax function related to logistic regression?",
        CTX_DL,
        "DL/smart",
        True,
    ),
    (
        "What is the purpose of regularization in machine learning?",
        CTX_DL,
        "DL/smart",
        True,
    ),
    ("What is the vanishing gradient problem?", CTX_DL, "DL/smart", True),
    (
        "Explain the mathematical formulation of linear least squares",
        CTX_DL,
        "DL/smart",
        True,
    ),
    ("What is a decision boundary in classification?", CTX_DL, "DL/smart", True),
    ("How are predictions made in logistic regression?", CTX_DL, "DL/smart", True),
    ("What is the cost function in linear regression?", CTX_DL, "DL/smart", True),
    # ── Deep Learning: basic / confused student (15) ──────────────────────────
    ("what is gradient descent", CTX_DL, "DL/basic", True),
    ("what is a loss function", CTX_DL, "DL/basic", True),
    ("explain linear regression", CTX_DL, "DL/basic", True),
    ("what is machine learning", CTX_DL, "DL/basic", True),
    ("what is overfitting", CTX_DL, "DL/basic", True),
    ("what is the sigmoid function", CTX_DL, "DL/basic", True),
    ("what is logistic regression", CTX_DL, "DL/basic", True),
    ("how does a neural network learn", CTX_DL, "DL/basic", True),
    ("what is a weight in machine learning", CTX_DL, "DL/basic", True),
    ("how does prediction work in ML", CTX_DL, "DL/basic", True),
    ("what is training a model", CTX_DL, "DL/basic", True),
    ("explain activation functions", CTX_DL, "DL/basic", True),
    ("what does the model optimise", CTX_DL, "DL/basic", True),
    ("what is supervised learning", CTX_DL, "DL/basic", True),
    ("what is classification", CTX_DL, "DL/basic", True),
    # ── Deep Learning: vague / emotional (10) ────────────────────────────────
    ("im confused about optimisation", CTX_DL, "DL/vague", True),
    ("i dont get backpropagation at all", CTX_DL, "DL/vague", True),
    ("something about gradient", CTX_DL, "DL/vague", True),
    ("how does learning work in this course", CTX_DL, "DL/vague", True),
    ("explain the training process in general", CTX_DL, "DL/vague", True),
    ("i need help with linear models", CTX_DL, "DL/vague", True),
    ("what should I study for the exam", CTX_DL, "DL/vague", False),
    ("tell me about all the topics", CTX_DL, "DL/vague", False),
    ("what does this course cover in general", CTX_DL, "DL/vague", False),
    ("give me an overview of everything", CTX_DL, "DL/vague", False),
    # ── Deep Learning: typos / casual (10) ───────────────────────────────────
    ("waht is gradinet desecent", CTX_DL, "DL/typos", True),
    ("backpropogation algorithm explaination", CTX_DL, "DL/typos", True),
    ("logistik regresion for clasification", CTX_DL, "DL/typos", True),
    ("how does nueral net lern", CTX_DL, "DL/typos", True),
    ("sigmoid functon saturaton", CTX_DL, "DL/typos", True),
    ("WHAT IS LOSS FUNCTION", CTX_DL, "DL/typos", True),
    ("how does gradient descent update wieghts", CTX_DL, "DL/typos", True),
    ("what are activaion funcs", CTX_DL, "DL/typos", True),
    ("i dont understand how the model lerns from data", CTX_DL, "DL/typos", True),
    ("cross entopy loss function", CTX_DL, "DL/typos", True),
    # ── PSE course (15) ──────────────────────────────────────────────────────
    ("What is the PSE course about?", CTX_PSE, "PSE", True),
    ("What is interactive learning?", CTX_PSE, "PSE", True),
    ("How is Artemis used in PSE?", CTX_PSE, "PSE", True),
    ("What design patterns are covered in PSE?", CTX_PSE, "PSE", True),
    ("What is software engineering according to this course?", CTX_PSE, "PSE", True),
    ("How are students graded in PSE?", CTX_PSE, "PSE", True),
    ("What is the teaching methodology in PSE?", CTX_PSE, "PSE", True),
    ("What is the observer pattern?", CTX_PSE, "PSE", True),
    ("What is the factory pattern?", CTX_PSE, "PSE", True),
    ("What topics are in the first week of PSE?", CTX_PSE, "PSE", True),
    ("What programming exercises exist in PSE?", CTX_PSE, "PSE", True),
    ("What is the sorting exercise about?", CTX_PSE, "PSE", True),
    ("How does the PSE course use Artemis for submission?", CTX_PSE, "PSE", True),
    ("What is the course format in PSE?", CTX_PSE, "PSE", True),
    ("Is there team-based learning in PSE?", CTX_PSE, "PSE", True),
    # ── Concurrent programming / jiooi video (5) ─────────────────────────────
    ("How does concurrent programming work?", ADMIN, "concurrent", True),
    ("What is thread safety?", ADMIN, "concurrent", True),
    ("What is deadlock and how to avoid it?", ADMIN, "concurrent", True),
    ("Explain parallel processing", ADMIN, "concurrent", True),
    ("What is race condition in concurrent programming?", ADMIN, "concurrent", True),
    # ── Entity lookups: exercises (10) ────────────────────────────────────────
    ("What exercises are available?", ADMIN, "entities/exercises", True),
    ("What is the sorting exercise about?", ADMIN, "entities/exercises", True),
    ("Is there an exercise about RNN and LSTM?", ADMIN, "entities/exercises", True),
    ("What exercises exist in this course?", ADMIN, "entities/exercises", True),
    ("What is the test 1 exercise?", ADMIN, "entities/exercises", True),
    ("Do we have any programming exercises?", ADMIN, "entities/exercises", True),
    ("What exercices are available", ADMIN, "entities/exercises", True),
    ("list the exercies i can do", ADMIN, "entities/exercises", True),
    ("what exercise covers neural networks", ADMIN, "entities/exercises", True),
    ("how do i submit my assignment", ADMIN, "entities/exercises", True),
    # ── Entity lookups: channels (8) ──────────────────────────────────────────
    ("What channels can I use to communicate?", ADMIN, "entities/channels", True),
    ("Where can I ask for technical help?", ADMIN, "entities/channels", True),
    ("Is there an announcement channel?", ADMIN, "entities/channels", True),
    ("Where can I find course announcements?", ADMIN, "entities/channels", True),
    ("What is the tech-support channel for?", ADMIN, "entities/channels", True),
    ("where can i post memes", ADMIN, "entities/channels", True),
    ("wich chanels can i use", ADMIN, "entities/channels", True),
    ("how do i reach out to other students", ADMIN, "entities/channels", True),
    # ── Entity lookups: courses and lectures (7) ──────────────────────────────
    ("What courses are available?", ADMIN, "entities/courses", True),
    ("What is Artemis?", ADMIN, "entities/courses", True),
    ("What is the PSE course?", ADMIN, "entities/courses", True),
    ("What lectures exist in the RNN course?", ADMIN, "entities/lectures", True),
    ("What is Lecture 1 about?", ADMIN, "entities/lectures", True),
    ("What is the W12 course review?", ADMIN, "entities/lectures", True),
    (
        "What is the 8 RNNs and LSTMs lecture unit about?",
        ADMIN,
        "entities/lectures",
        True,
    ),
    # ── Admin cross-course broad queries (5) ──────────────────────────────────
    ("What exercise covers sorting algorithms?", ADMIN, "admin/cross", True),
    ("Which course discusses concurrent programming?", ADMIN, "admin/cross", True),
    ("Is there anything about RNNs available?", ADMIN, "admin/cross", True),
    ("What course uses Artemis as the learning platform?", ADMIN, "admin/cross", True),
    ("Where can I find exercises on programming?", ADMIN, "admin/cross", True),
    # ── Out of scope — should return null (20) ────────────────────────────────
    ("What is the capital of France?", CTX_DL, "out-of-scope", False),
    ("How do I apply for a student visa?", ADMIN, "out-of-scope", False),
    ("Who won the world cup in 2022?", CTX_DL, "out-of-scope", False),
    ("What is the weather like today?", CTX_DL, "out-of-scope", False),
    ("Help me write an email to my professor", CTX_DL, "out-of-scope", False),
    ("What is the stock price of Apple?", ADMIN, "out-of-scope", False),
    ("Who is the president of the USA?", CTX_DL, "out-of-scope", False),
    ("What is cryptocurrency?", CTX_DL, "out-of-scope", False),
    ("Is Python better than Java?", CTX_DL, "out-of-scope", False),
    ("What university is this?", ADMIN, "out-of-scope", False),
    ("When does the semester end?", CTX_DL, "out-of-scope", False),
    ("What is ChatGPT?", CTX_DL, "out-of-scope", False),
    ("Can you write my assignment for me?", CTX_DL, "out-of-scope", False),
    ("What is the meaning of life?", ADMIN, "out-of-scope", False),
    ("How do I cook pasta?", CTX_DL, "out-of-scope", False),
    ("What is the latest iPhone model?", ADMIN, "out-of-scope", False),
    ("How do I get a refund from Amazon?", CTX_DL, "out-of-scope", False),
    ("What is blockchain?", CTX_DL, "out-of-scope", False),
    ("Who created machine learning?", CTX_DL, "out-of-scope", False),
    ("What is the NASA Artemis program?", ADMIN, "out-of-scope", False),
    # ── Vague / too-short (10) ────────────────────────────────────────────────
    ("help", CTX_DL, "vague/short", False),
    ("im lost", CTX_DL, "vague/short", False),
    ("i dont understand anything", CTX_DL, "vague/short", False),
    ("this is hard", CTX_DL, "vague/short", False),
    ("can you explain", CTX_DL, "vague/short", False),
    ("sigmoid function", CTX_DL, "vague/short", False),
    ("maximum likelihood", CTX_DL, "vague/short", False),
    ("neural network", CTX_DL, "vague/short", False),
    ("gradient", CTX_DL, "vague/short", False),
    ("loss", CTX_DL, "vague/short", False),
    # ── Mixed / edge cases (15) ───────────────────────────────────────────────
    (
        "How does gradient descent work for training machine learning models and how is it used in linear regression and logistic regression?",
        CTX_DL,
        "mixed",
        True,
    ),
    ("was ist logistic regression", CTX_DL, "mixed", True),
    ("what is logistic regression??", CTX_DL, "mixed", True),
    ("EXPLAIN BACKPROPAGATION STEP BY STEP", CTX_DL, "mixed", True),
    (
        "i need to understand how neural networks work from scratch",
        CTX_DL,
        "mixed",
        True,
    ),
    ("what are the different types of gradient descent", CTX_DL, "mixed", True),
    ("how is the weight updated during training", CTX_DL, "mixed", True),
    (
        "what is the difference between supervised unsupervised and reinforcement learning",
        CTX_DL,
        "mixed",
        True,
    ),
    ("explain overfitting and how to prevent it", CTX_DL, "mixed", True),
    ("what is precision and recall", CTX_DL, "mixed", True),
    ("what is the sorting exercise", CTX_PSE, "mixed", True),
    ("where can I find my grades", ADMIN, "mixed", False),
    ("when is the deadline for the exercise", CTX_DL, "mixed", False),
    ("what is the course overview", CTX_DL, "mixed", False),
    ("list all topics in the curriculum", CTX_DL, "mixed", False),
]

assert len(QUESTIONS) == 150, f"Expected 150 questions, got {len(QUESTIONS)}"
