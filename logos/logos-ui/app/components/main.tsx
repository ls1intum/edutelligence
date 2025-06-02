import React, { useContext } from 'react';
import { Dimensions, StyleSheet, Text, View } from 'react-native';
import { ThemeContext } from '../';

export default function Main() {
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';

  return (
    <View style={styles.wrapper}>
      <View
        style={[
          styles.placeholderContainer,
          {
            borderColor: isLight ? '#cccccc' : '#555555',
            backgroundColor: isLight ? '#fafafa' : '#1f1f1f'
          }
        ]}
      >
        <Text
          style={[
            styles.placeholderText,
            { color: isLight ? '#111111' : '#f0f0f0' }
          ]}
        >
          Placeholder for Main Content
        </Text>
      </View>
    </View>
  );
}

const { height: SCREEN_HEIGHT } = Dimensions.get('window');
const styles = StyleSheet.create({
  wrapper: {
    flex: 1,
    padding: 12
  },
  placeholderContainer: {
    flex: 1,
    borderWidth: 2,
    borderStyle: 'dashed',
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    // Wir nutzen hier fast die komplette Höhe minus Header/Footer;
    // Da wir Flex verwenden, passt es sich automatisch an.
  },
  placeholderText: {
    fontSize: 18
  }
});
