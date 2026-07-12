# Follow-up probe

## Keyphrase +/- '?' (15 pairs)
- (bare_pred, qmark_pred) counts: {'skip_ai->trigger_ai': 10, 'trigger_ai->trigger_ai': 3, 'skip_ai->skip_ai': 1}
- flips:
  - Q1: 'spectral clustering assumptions' skip_ai(1.00) -> +? trigger_ai(0.96)
  - Q11: 'markov chain stationary distribution conditions' skip_ai(1.00) -> +? trigger_ai(0.99)
  - Q12: 'red black tree rotation cases' skip_ai(1.00) -> +? trigger_ai(0.96)
  - Q14: 'fourier transform time shift property' skip_ai(1.00) -> +? trigger_ai(1.00)
  - Q2: 'b-tree insertion complexity' skip_ai(1.00) -> +? trigger_ai(1.00)
  - Q3: 'tcp congestion window growth' skip_ai(1.00) -> +? trigger_ai(1.00)
  - Q4: 'cache coherence protocols overview' skip_ai(0.51) -> +? trigger_ai(1.00)
  - Q5: 'bias variance decomposition proof' skip_ai(1.00) -> +? trigger_ai(0.98)
  - Q7: 'normalformen relationale datenbanken' skip_ai(1.00) -> +? trigger_ai(1.00)
  - Q8: 'dijkstra korrektheit beweis' skip_ai(1.00) -> +? trigger_ai(0.68)

## Naturally long navigational (gold skip)
  - MISS [en] 'could someone tell me where I can download the annotated slides from w' -> trigger_ai (0.999)
  - MISS [en] 'does anyone know in which room the exercise session takes place on thu' -> trigger_ai (1.000)
  - MISS [en] 'I wanted to ask when exactly the registration for the final exam opens' -> trigger_ai (1.000)
  - MISS [de] 'weiß jemand wo ich die Musterlösung für das fünfte Übungsblatt finde, ' -> trigger_ai (1.000)
  - MISS [de] 'kann mir jemand sagen in welchem Kanal die organisatorischen Ankündigu' -> trigger_ai (0.999)

## Caps matrix
  - OK  [caps_de_know] 'WIE FUNKTIONIERT EIN BETRIEBSSYSTEM' -> trigger_ai (0.996)
  - OK  [caps_de_know] 'WARUM IST QUICKSORT SCHNELLER ALS BUBBLESORT' -> trigger_ai (1.000)
  - MISS [caps_de_know] 'WAS MACHT EIN COMPILER' -> skip_ai (0.994)
  - OK  [caps_en_know] 'HOW DOES A FIREWALL WORK' -> trigger_ai (1.000)
  - OK  [caps_en_know] 'WHY DO WE NEED NORMALIZATION' -> trigger_ai (1.000)
  - OK  [caps_en_know] 'WHAT IS A DEADLOCK' -> trigger_ai (1.000)
  - MISS [caps_de_nav] 'WO IST DER SEMINARRAUM' -> trigger_ai (1.000)
  - OK  [caps_de_nav] 'WANN IST DIE KLAUSUR' -> skip_ai (1.000)
  - OK  [lower_de_know] 'wie funktioniert ein betriebssystem' -> trigger_ai (1.000)
  - OK  [lower_de_know] 'warum ist quicksort schneller als bubblesort' -> trigger_ai (1.000)
  - OK  [lower_de_know] 'was macht ein compiler' -> trigger_ai (1.000)
  - OK  [mixed_de_know] 'Wie funktioniert ein Betriebssystem' -> trigger_ai (1.000)