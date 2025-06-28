import React, {useContext} from 'react';
import { View, Text, StyleSheet, useWindowDimensions } from 'react-native';
import { Trophy, Bot, Check } from 'lucide-react';
import { ThemeContext } from './theme';

export default function Section02() {
  const { width } = useWindowDimensions();
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';

  return (
    <View style={[styles.container, { backgroundColor: isLight ? '#ffffff' : '#000000' }]}>
      <View style={styles.header}>
        <Text style={[styles.badge, {backgroundColor: isLight ? '#ececec' : '#111827', color: isLight ? '#000' : '#fff'}]}>Key Features</Text>
        <Text style={[styles.headline, {color: isLight ? '#000' : '#fff'}]}>Your Central Hub for LLM Management</Text>
        <Text style={[styles.subtext, {color: isLight ? '#000' : '#fff'}]}>
          Streamline your LLM workflows and gain actionable intelligence
        </Text>
      </View>
      <View style={[styles.cardContainer]}>
        <FeatureCard
          icon={<Trophy color="#facc15" size={24} />}
          title="Available Tools"
          description="Control your entire LLM workflow"
          bullets={[
            'Prompt Classification',
            'Policy Classification',
            'Provider Routing',
          ]}
        />
        <FeatureCard
          icon={<Bot color="#38bdf8" size={24} />}
          title="Data & APIs"
          description="Analyze and observe AI usage"
          bullets={[
            'gRPC Interface',
            'Detailed Usage Statistics',
            'Model Analytics',
          ]}
        />
      </View>
    </View>
  );
}

// @ts-ignore
function FeatureCard({ icon, title, description, bullets }) {
  const { theme } = useContext(ThemeContext);
  const isLight = theme === 'light';
  return (
    <View style={[styles.card, { backgroundColor: isLight ? '#dedede' : '#111827' }]}>
      <View style={styles.cardHeader}>
        {icon}
        <Text style={[styles.cardTitle, {color: isLight ? '#000' : '#fff'}]}>{title}</Text>
      </View>
      <Text style={[styles.cardDescription, {color: isLight ? '#000' : '#fff'}]}>{description}</Text>
      <View style={styles.bulletList}>
        {bullets.map((text: string | number | bigint | boolean | React.ReactElement<unknown, string | React.JSXElementConstructor<any>> | Iterable<React.ReactNode> | React.ReactPortal | Promise<string | number | bigint | boolean | React.ReactPortal | React.ReactElement<unknown, string | React.JSXElementConstructor<any>> | Iterable<React.ReactNode> | null | undefined> | null | undefined, i: React.Key | null | undefined) => (
          <View key={i} style={styles.bulletItem}>
            <Check color="#22c55e" size={18} />
            <Text style={[styles.bulletText, {color: isLight ? '#000' : '#fff'}]}>{text}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingVertical: 80,
    paddingHorizontal: 24,
    backgroundColor: '#0a0a0a',
    alignItems: 'center',
  },
  header: {
    alignItems: 'center',
    marginBottom: 40,
  },
  badge: {
    backgroundColor: '#1f2937',
    color: '#fff',
    paddingHorizontal: 12,
    paddingVertical: 4,
    fontSize: 12,
    borderRadius: 999,
    marginBottom: 10,
  },
  headline: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
    marginBottom: 10,
    textAlign: 'center',
  },
  subtext: {
    color: '#9ca3af',
    fontSize: 16,
    textAlign: 'center',
  },
  card: {
    backgroundColor: '#111827',
    borderRadius: 16,
    padding: 24,
    width: 500,
    display: "flex",
    justifyContent: "space-between",
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  cardTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  cardDescription: {
    color: '#545454',
    marginBottom: 16,
  },
  bulletList: {
    gap: 8,
  },
  bulletItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  bulletText: {
    color: '#e5e7eb',
    fontSize: 14,
  },
  cardContainer: {
    gap: 24,
    justifyContent: 'center',
    flexDirection: "row"
  },
});
