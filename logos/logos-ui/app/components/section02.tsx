import React from 'react';
import { View, Text, StyleSheet, useWindowDimensions } from 'react-native';
import { Trophy, Bot, Check } from 'lucide-react';

export default function FeaturesSection() {
  const { width } = useWindowDimensions();
  const isMobile = width < 768;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.badge}>Key Features</Text>
        <Text style={styles.headline}>Tools for Team Growth</Text>
        <Text style={styles.subtext}>
          Features designed to elevate your engineering team's collaboration and learning
        </Text>
      </View>

      <View style={[styles.cardContainer, { flexDirection: isMobile ? 'column' : 'row' }]}>
        <FeatureCard
          icon={<Trophy color="#facc15" size={24} />}
          title="Code Review Gamification"
          description="Transform code reviews into learning opportunities"
          bullets={[
            'Weekly leaderboards with GitHub integration',
            'Team competitions across multiple repositories',
            'Structured league system for ongoing engagement',
          ]}
        />
        <FeatureCard
          icon={<Bot color="#38bdf8" size={24} />}
          title="AI-Powered Mentorship"
          description="Personalized guidance for improvement"
          bullets={[
            'Weekly reflective sessions for improvement',
            'GitHub activity analysis for context-aware feedback',
            'Goal-setting framework with progress tracking',
          ]}
        />
      </View>
    </View>
  );
}

function FeatureCard({ icon, title, description, bullets }) {
  return (
    <View style={styles.card}>
      <View style={styles.cardHeader}>
        {icon}
        <Text style={styles.cardTitle}>{title}</Text>
      </View>
      <Text style={styles.cardDescription}>{description}</Text>
      <View style={styles.bulletList}>
        {bullets.map((text, i) => (
          <View key={i} style={styles.bulletItem}>
            <Check color="#22c55e" size={18} />
            <Text style={styles.bulletText}>{text}</Text>
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
  cardContainer: {
    gap: 24,
    justifyContent: 'center',
  },
  card: {
    backgroundColor: '#111827',
    borderRadius: 16,
    padding: 24,
    width: 360,
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
    color: '#9ca3af',
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
});
