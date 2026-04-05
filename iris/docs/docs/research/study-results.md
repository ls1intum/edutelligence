---
title: Study Results
---

# Study Results

Iris has been evaluated in three peer-reviewed studies, progressing from an initial survey-based assessment through a small mixed-methods study to a large randomized controlled trial. This page presents the findings from each study with exact numbers from the published papers.

## ITiCSE 2024: Initial Survey Evaluation (N=121)

**Bassner, Frankford & Krusche (2024).** Survey-based evaluation conducted across three CS1-level courses at TUM (Management & Technology, Informatics, Information Engineering). Of 1,655 enrolled students, 221 engaged with Iris (10+ messages), and 121 completed the survey (55% response rate).

### Perceived Effectiveness (RQ1)

| Survey Item                                              | Agreement |
| -------------------------------------------------------- | --------- |
| Iris comprehends my inquiries well (Q1)                  | 46%       |
| Iris directly helps with exercises (Q2)                  | 44%       |
| Iris enhanced understanding of programming concepts (Q3) | 50%       |
| Interactions with Iris are engaging (Q4)                 | 60%       |

### Comfort Compared to Human Tutors (RQ2)

| Survey Item                                        | Agreement |
| -------------------------------------------------- | --------- |
| Comfortable asking questions without judgment (Q6) | 92%       |
| Feel safe asking sensitive questions (Q7)          | 62%       |

### Subjective Reliance (RQ3)

43% of students reported they would find it challenging to solve exercises without Iris (Q10). Students predominantly viewed Iris as a **complement to**, not a replacement for, human tutors.

### Limitations

- Self-report data only; no objective learning measures
- Selection bias: only students who used Iris substantially participated
- Single institution (TUM), CS1 courses only

---

## Koli Calling '25: Mixed-Methods Study (N=33)

**Bassner, Lottner & Krusche (2025).** Exploratory randomized between-subjects study where 33 students implemented the Burrows-Wheeler Transform in Java under three conditions: Iris, ChatGPT, or No AI. Combined quantitative performance measures with systematic qualitative analysis of post-task interviews.

### Quantitative Results

No statistically significant differences were found between conditions in:

- Learning gains (pre-test to post-test)
- Task completion time
- Code accuracy

:::note
The small sample size (N=33) limits statistical power. The study was designed as exploratory, with the qualitative component as its primary contribution.
:::

### Qualitative Themes

Five themes emerged from the interview analysis:

1. **Time pressure dominated tool selection.** Students prioritized efficiency over learning when under time constraints, regardless of condition. This suggests that the study setting itself may influence how students interact with AI tools.

2. **Context-aware guidance was universally appreciated.** Students in the Iris condition valued that the tutor already understood their exercise and code, eliminating the need to provide context manually.

3. **Polarized scaffolding preferences.** Some students wanted more explicit hints from Iris, while others appreciated the restraint. This suggests that a one-size-fits-all scaffolding level may not serve all learners equally.

4. **ChatGPT users sought external verification more.** Students using ChatGPT more frequently sought confirmation of AI-generated answers from other sources, suggesting lower trust in the correctness of responses compared to Iris users.

5. **Over-reliance concerns were prevalent.** Students across AI conditions expressed worry about becoming dependent on AI assistance, with ChatGPT users expressing stronger concerns about this than Iris users.

### Limitations

- Small sample size (N=33) limits generalizability
- Single programming task (Burrows-Wheeler Transform)
- Lab setting with time pressure may not reflect naturalistic use

---

## C&E:AI 2026: Randomized Controlled Trial (N=275)

**Bassner, Lenk-Ostendorf, Beinstingel, Wasner & Krusche (2026).** Three-arm RCT conducted in a CS1 course at TUM. Students completed a 90-minute concurrent programming exercise (parallel sum with threading). After quality filters, 275 participants remained: Iris (n=91), ChatGPT (n=88), No AI (n=96).

This is the largest and most rigorous evaluation of Iris to date.

### Finding 1: AI as Performance Enhancer, Not Learning Enhancer

Both AI tools significantly boosted exercise performance compared to the No AI condition, but **neither improved learning outcomes**.

**Exercise Performance:**

| Condition | Mean (%) | SD    |
| --------- | -------- | ----- |
| ChatGPT   | 71.84    | 39.65 |
| Iris      | 57.50    | 37.36 |
| No AI     | 29.85    | 36.17 |

ANOVA: _p_ < .001, _eta_^2 = .179

| Comparison       | Cohen's _d_ | _p_    |
| ---------------- | ----------- | ------ |
| ChatGPT vs No AI | 1.10        | < .001 |
| Iris vs No AI    | 0.76        | < .001 |
| ChatGPT vs Iris  | 0.38        | .031   |

**Knowledge Assessment (Learning):** No significant group differences (_p_ = .311). All three groups improved significantly from pre-test to post-test (_p_ < .001). AI tools did **not** differentially affect knowledge acquisition.

**Code Comprehension:** No significant differences between conditions (_p_ = .136).

:::caution Key Implication
Higher exercise scores with AI assistance do not necessarily indicate deeper learning. The dissociation between performance and learning is a central finding of this study.
:::

### Finding 2: Iris Balances Scaffolding and Cognitive Challenge

The distribution of exercise scores differed qualitatively between conditions:

- **ChatGPT** scores clustered at the high end of the scale
- **No AI** scores clustered at the low end
- **Iris** scores spread across the full range

This pattern suggests that Iris preserved individual performance variation --- students who understood the material performed well, while those who struggled still had to engage with the problem. ChatGPT, by contrast, compressed performance toward the top of the scale.

### Finding 3: Iris Uniquely Improves Intrinsic Motivation

**Frustration (lower is better):**

| Condition | Mean | SD   |
| --------- | ---- | ---- |
| ChatGPT   | 3.13 | 1.21 |
| Iris      | 3.21 | 1.18 |
| No AI     | 4.09 | 1.00 |

| Comparison       | Cohen's _d_ | _p_    |
| ---------------- | ----------- | ------ |
| ChatGPT vs No AI | −0.87       | < .001 |
| Iris vs No AI    | −0.81       | < .001 |
| ChatGPT vs Iris  | −0.07       | .886   |

Both AI tools significantly reduced frustration compared to No AI. There was no meaningful difference in frustration between ChatGPT and Iris.

**Intrinsic Motivation (higher is better):**

| Condition | Mean | SD   |
| --------- | ---- | ---- |
| Iris      | 2.82 | 0.70 |
| ChatGPT   | 2.64 | 0.65 |
| No AI     | 2.42 | 0.74 |

| Comparison       | Cohen's _d_ | _p_    |
| ---------------- | ----------- | ------ |
| Iris vs No AI    | 0.55        | < .001 |
| ChatGPT vs No AI | 0.32        | .076   |
| ChatGPT vs Iris  | −0.25       | .234   |

**Only Iris** significantly increased intrinsic motivation compared to the No AI condition. ChatGPT did not reach significance (_p_ = .076). This is notable because both tools reduced frustration equally, but only Iris additionally enhanced engagement.

### Finding 4: ChatGPT as a "Comfort Trap"

Students rated ChatGPT more favorably on several perception measures:

| Perception Item                | ChatGPT | Iris | Cohen's _d_ | _p_    |
| ------------------------------ | ------- | ---- | ----------- | ------ |
| Easy to use                    | 4.36    | 3.97 | 0.45        | .003   |
| Feedback helpful               | 3.98    | 3.54 | 0.44        | .004   |
| Helped resolve exercise issues | 4.08    | 3.49 | 0.63        | < .001 |
| General helpfulness            | n.s.    | n.s. | ---         | .351   |

Despite these more favorable perceptions, ChatGPT users did **not** achieve better learning outcomes than Iris users. The authors characterize this pattern as a "comfort trap" --- students preferred the tool that felt easier and more helpful, but these subjective preferences aligned with greater reductions in learning-related cognitive processing rather than with actual learning gains.

### Limitations

- Single institution, single course, single programming task (concurrent programming)
- 90-minute lab setting may not reflect semester-long usage patterns
- Attrition from 452 to 275 participants after quality filters
- No long-term follow-up on retention or transfer

---

## Summary Across Studies

| Dimension       | ITiCSE '24                        | Koli '25                   | C&E:AI '26                  |
| --------------- | --------------------------------- | -------------------------- | --------------------------- |
| **Design**      | Survey                            | Mixed-methods RCT          | Three-arm RCT               |
| **N**           | 121                               | 33                         | 275                         |
| **Performance** | Self-reported benefit             | No significant differences | Iris > No AI (_d_ = 0.76)   |
| **Learning**    | Not measured                      | No significant differences | No significant differences  |
| **Motivation**  | 60% found interactions engaging   | Not measured               | Iris > No AI (_d_ = 0.55)   |
| **Frustration** | Not measured                      | Not measured               | Iris < No AI (_d_ = −0.81)  |
| **Comfort**     | 92% comfortable (vs human tutors) | Context awareness valued   | ChatGPT rated easier to use |

For full citations and BibTeX entries, see [Publications](./publications.md).
