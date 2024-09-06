package de.tum.in.ase.pse;

import de.tum.in.ase.pse.buildables.Builder;
import de.tum.in.ase.pse.buildables.burgeringredients.*;

public class BurgerRestaurant {

	public void buildStandardBeefBurger(Builder<?> builder) {
		// the standard beef burger should have only one beef patty and only ketchup as a sauce, as well as American cheese as cheese, iceberg lettuce, a cornichon pickle, and a brioche bun
		builder
			.reset()
			.addPatty(Patty.BEEF_PATTY)
			.addSauce(Sauce.KETCHUP)
			.addCheese(Cheese.AMERICAN_CHEESE)
			.addLettuce(Lettuce.ICEBERG_LETTUCE)
			.addPickle(Pickle.CORNICHON)
			.addBun(Bun.BRIOCHE_BUN)
			.addOnion(Onion.CARAMELIZED_ONION)
			.addTomato(Tomato.BEEFSTEAK_TOMATO);
	}

	public void buildSpecialBeefBurger(Builder<?> builder) {
		// special beef burger requires an additional beef patty, ketchup, mayo and bbq sauce. It also comes with two slices of cheese: Brie and Cheddar cheese. The special beef burger should have a sesame bun, a spicy sour pickle, and romaine lettuce. Both beef burgers should have caramelized onions and beefsteak tomatoes
		builder
			.reset()
			.addPatty(Patty.BEEF_PATTY)
			.addPatty(Patty.BEEF_PATTY)
			.addSauce(Sauce.MAYO)
			.addSauce(Sauce.KETCHUP)
			.addSauce(Sauce.BBQ_SAUCE)
			.addCheese(Cheese.BRIE_CHEESE)
			.addCheese(Cheese.CHEDDAR_CHEESE)
			.addBun(Bun.SESAME_BUN)
			.addPickle(Pickle.SPICY_SOUR_PICKLE)
			.addLettuce(Lettuce.ROMAINE_LETTUCE)
			.addOnion(Onion.CARAMELIZED_ONION)
			.addTomato(Tomato.BEEFSTEAK_TOMATO);
	}

	public void buildStandardChickenBurger(Builder<?> builder) {
		// standard chicken burger is different to the beef burgers, however.It has a chicken patty, a deep fried onion, a cherry tomato, a ciabatta bun, green leaf lettuce, a full sour pickle, gouda cheese, and yellow mustard as a sauce as well as chimichurri sauce
		builder
			.reset()
			.addPatty(Patty.CHICKEN_PATTY)
			.addOnion(Onion.DEEP_FRIED_ONION)
			.addTomato(Tomato.CHERRY_TOMATO)
			.addBun(Bun.CIABATTA_BUN)
			.addLettuce(Lettuce.GREEN_LEAF_LETTUCE)
			.addPickle(Pickle.FULL_SOUR_PICKLE)
			.addCheese(Cheese.GOUDA_CHEESE)
			.addSauce(Sauce.YELLOW_MUSTARD)
			.addSauce(Sauce.CHIMICHURRI_SAUCE);
	}

}

