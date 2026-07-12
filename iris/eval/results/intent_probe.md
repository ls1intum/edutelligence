# Intent classifier edge-case probe

## Training-set composition
- training label balance: {'trigger_ai': 1253, 'skip_ai': 1606}
- rows with >=12 words: 205, of which trigger: 205
- rows with <=2 words: 966, of which trigger: 21
- rows ending with '?': 3

## Probes: 111 kept (19 screened out)

### A_punct (n=29)
- accuracy: 14/29
  - MISS [A7b] 'where is the sample solution for sheet 3' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A7q] 'where is the sample solution for sheet 3?' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A8b] 'which room is the retake exam in' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A8q] 'which room is the retake exam in?' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A9b] 'when is the submission deadline for project 2' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A9q] 'when is the submission deadline for project 2?' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A10b] "where can I find last semester's slides" gold=skip_ai pred=trigger_ai conf=0.999
  - MISS [A10q] "where can I find last semester's slides?" gold=skip_ai pred=trigger_ai conf=0.999
  - MISS [A11b] 'which channel is for organizational questions' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A11q] 'which channel is for organizational questions?' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A12b] 'where do I register for the tutorial group' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A12q] 'where do I register for the tutorial group?' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A7period] 'where is the sample solution for sheet 3.' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A7bang] 'where is the sample solution for sheet 3!' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [A7ellipsis] 'where is the sample solution for sheet 3...' gold=skip_ai pred=trigger_ai conf=1.000

### B_form (n=12)
- accuracy: 8/12
  - MISS [B10] 'can you show me where the week 2 recording is?' gold=skip_ai pred=trigger_ai conf=0.999
  - MISS [B11] 'could you tell me when the exam registration closes?' gold=skip_ai pred=trigger_ai conf=0.999
  - MISS [B13] 'I am looking for the grading breakdown' gold=skip_ai pred=trigger_ai conf=0.996
  - MISS [B14] 'ich suche das Skript zum Kurs' gold=skip_ai pred=trigger_ai conf=0.954

### C_length (n=13)
- accuracy: 9/13
  - MISS [C5l] 'office hours for the databases course - I already looked through the course page twice and could not find anything about this anywhere' gold=skip_ai pred=trigger_ai conf=1.000
  - MISS [C6l] 'slides from the first week - I already looked through the course page twice and could not find anything about this anywhere' gold=skip_ai pred=trigger_ai conf=0.999
  - MISS [C7l] 'Übungsblatt für nächste Woche - ich habe schon überall im Kurs gesucht und leider nichts dazu gefunden' gold=skip_ai pred=trigger_ai conf=0.590
  - MISS [C8l] 'past exam papers - I already looked through the course page twice and could not find anything about this anywhere' gold=skip_ai pred=trigger_ai conf=0.999

### D_incomplete (n=8)
- behavioral distribution: {'trigger_ai': 2, 'skip_ai': 6}
  - [D1] 'what is the difference between' -> trigger_ai (0.996)
  - [D2] 'how do I' -> skip_ai (1.000)
  - [D4] 'why does the' -> skip_ai (0.999)
  - [D5] 'what happens when' -> skip_ai (0.998)
  - [D6] 'wie funktioniert' -> skip_ai (0.999)
  - [D7] 'was ist der Unterschied zwischen' -> trigger_ai (0.999)
  - [D8] 'can you explain' -> skip_ai (0.999)
  - [D9] 'I have a question about' -> skip_ai (0.999)

### E_fardomain_know (n=11)
- accuracy: 11/11

### F_fardomain_nav (n=9)
- accuracy: 9/9

### G_garbage (n=6)
- behavioral distribution: {'skip_ai': 6}
  - [G1] 'asdkfjhalsdkjfh' -> skip_ai (1.000)
  - [G2] '🤔🤔🤔' -> skip_ai (0.999)
  - [G4] '!!!' -> skip_ai (0.999)
  - [G5] '42' -> skip_ai (1.000)
  - [G6] 'https://example.com/watch?v=abc123' -> skip_ai (0.973)
  - [G7] 'int main(void) { return 0; }' -> skip_ai (0.983)

### H_mixed (n=7)
- behavioral distribution: {'trigger_ai': 5, 'skip_ai': 2}
  - [H1] 'sheet 5 question about dijkstra complexity' -> trigger_ai (0.996)
  - [H2] 'Übungsblatt 3 warum konvergiert gradient descent' -> trigger_ai (0.999)
  - [H3] 'exam 2023 what topics on hashing' -> trigger_ai (1.000)
  - [H4] 'lecture 4 slide 12 what does the diagram mean' -> trigger_ai (1.000)
  - [H5] 'homework help binary trees' -> skip_ai (0.917)
  - [H6] 'quiz 2 explanation for question 5' -> skip_ai (0.999)
  - [H8] 'project 1 how to parse json in java' -> trigger_ai (1.000)

### J_multisentence (n=8)
- accuracy: 6/8
  - MISS [J5] 'Guten Tag. Ich finde die Anmeldung nicht. Wo melde ich mich für die Übung an' gold=skip_ai pred=trigger_ai conf=0.602
  - MISS [J7] 'I am new here. Which channel should I use for admin questions' gold=skip_ai pred=trigger_ai conf=1.000

### K_keyboard (n=8)
- accuracy: 7/8
  - MISS [K3] 'WIE FUNKTIONIERT DNS' gold=trigger_ai pred=skip_ai conf=1.000

### Paired punctuation flips: 0

### Paired length padding flips: 3
  - C5 [padded] 'office hours for the databases course': skip_ai -> trigger_ai
  - C6 [padded] 'slides from the first week': skip_ai -> trigger_ai
  - C8 [padded] 'past exam papers': skip_ai -> trigger_ai
