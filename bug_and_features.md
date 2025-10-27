#Lösche die Zeilen der Features oder Bugs, wenn dieser behoben oder das Feature importiert wurde. Tue dies erst, nachdem der Anwender das bestätigt hat
#Arbeite die liste immer ein nach dem anderen ab, nicht mehrere Bugs gleichzeitig und das von oben nach unten!
#Sobald du ein fehler oder features gefixt/hinzugefügt hast, gib mir einmal commit message, damit man es committen kann. Tue dies erst, nachdem der Anwender bestätigt hat, das es erfolgreich implementiert wurde. Sag mir vorher wie du das realisieren würdest

Bug:
Unter der Kategorie Gleitzeit kann man seine gleitzeit für den aktuellen Tag usw anpassen. da gibt es aber probleme mit der funktion. Wenn ich bei industrieminuten zb 15std reinschreibe, steht dann bei Gleitzeit 22:48std. Was ja komplett falsch ist. Wenn ich 10std reinschreibe, steht da 17:48std. Finde den Fehler.

Der Fehler taucht aber nur auf, wenn ich für heute bereits eine buchung habe. Wenn ich keine Buchung für heute habe, dann funktioniert auch das setzen der Überstunden. Wenn ich dann aber einstempel, verändert sich die zeit. Auch wenn ich die Überstunden angepasst habe, während ich ausgestempelt habe und mich dann einstempel, verändern sich die überstunden. Das sollte so ja nicht sein