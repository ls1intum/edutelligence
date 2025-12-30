import React, { useState, useEffect } from 'react';
import { Image as ExpoImage } from 'expo-image';

import Footer from '@/components/footer';
import Header from '@/components/header';
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { Center } from "@/components/ui/center";

export default function About() {
  const [hue, setHue] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setHue(h => (h + 1) % 360);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
      <Center className="flex-1 p-6 w-full max-w-[800px]">
        <VStack space="md" className="items-center w-full">
            <ExpoImage
            source={require('../assets/images/logos_full.png')}
            style={{ width: 200, height: 90, filter: `hue-rotate(${hue}deg)` } as any}
            contentFit="contain"
            />
            <Text size="2xl" className="font-bold mb-6 text-black dark:text-white">
                About Logos
            </Text>
            <Text size="xl" className="text-center text-black dark:text-white leading-normal">
                Logos helps you organize and manage AI prompts by classifying and routing them to the right models – making it easier to build powerful, provider-agnostic AI workflows
            </Text>
        </VStack>
      </Center>
  );
}