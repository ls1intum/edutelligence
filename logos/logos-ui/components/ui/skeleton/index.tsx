import React, { forwardRef, useEffect, useMemo, useRef } from 'react';
import type { VariantProps } from '@gluestack-ui/utils/nativewind-utils';
import { Animated, Easing, Platform, View } from 'react-native';
import { skeletonStyle, skeletonTextStyle } from './styles';

type ISkeletonProps = React.ComponentProps<typeof View> &
  VariantProps<typeof skeletonStyle> & {
    isLoaded?: boolean;
    startColor?: string;
    speed?: number | string;
  };

type ISkeletonTextProps = React.ComponentProps<typeof View> &
  VariantProps<typeof skeletonTextStyle> & {
    _lines?: number;
    isLoaded?: boolean;
    startColor?: string;
  };

const Skeleton = forwardRef<
  React.ComponentRef<typeof Animated.View>,
  ISkeletonProps
>(function Skeleton(
  {
    className,
    variant,
    children,
    startColor = 'bg-background-200',
    isLoaded = false,
    speed = 2,
    ...props
  },
  ref
) {
  const pulseAnim = useRef(new Animated.Value(1)).current;
  const animationDuration = useMemo(() => {
    const fadeDuration = 0.6;
    const duration = (fadeDuration * 10000) / Number(speed || 1);
    return Number.isFinite(duration) ? duration : 2000;
  }, [speed]);

  useEffect(() => {
    const customTimingFunction = Easing.bezier(0.4, 0, 0.6, 1);
    const pulse = Animated.sequence([
      Animated.timing(pulseAnim, {
        toValue: 1,
        duration: animationDuration / 2,
        easing: customTimingFunction,
        useNativeDriver: Platform.OS !== 'web',
      }),
      Animated.timing(pulseAnim, {
        toValue: 0.75,
        duration: animationDuration / 2,
        easing: customTimingFunction,
        useNativeDriver: Platform.OS !== 'web',
      }),
      Animated.timing(pulseAnim, {
        toValue: 1,
        duration: animationDuration / 2,
        easing: customTimingFunction,
        useNativeDriver: Platform.OS !== 'web',
      }),
    ]);

    const loop = Animated.loop(pulse);

    if (!isLoaded) {
      loop.start();
    } else {
      loop.stop();
    }

    return () => {
      loop.stop();
    };
  }, [animationDuration, isLoaded, pulseAnim]);

  if (!isLoaded) {
    return (
      <Animated.View
        style={{ opacity: pulseAnim }}
        className={`${startColor} ${skeletonStyle({
          variant,
          class: className,
        })}`}
        {...props}
        ref={ref}
      />
    );
  } else {
    return children;
  }
});

const SkeletonText = forwardRef<
  React.ComponentRef<typeof View>,
  ISkeletonTextProps
>(function SkeletonText(
  {
    className,
    _lines,
    isLoaded = false,
    startColor = 'bg-background-200',
    gap = 2,
    children,
    ...props
  },
  ref
) {
  if (!isLoaded) {
    if (_lines) {
      return (
        <View
          className={`${skeletonTextStyle({
            gap,
          })}`}
          ref={ref}
        >
          {Array.from({ length: _lines }).map((_, index) => (
            <Skeleton
              key={index}
              className={`${startColor} ${skeletonTextStyle({
                class: className,
              })}`}
              {...props}
            />
          ))}
        </View>
      );
    } else {
      return (
        <Skeleton
          className={`${startColor} ${skeletonTextStyle({
            class: className,
          })}`}
          {...props}
          ref={ref}
        />
      );
    }
  } else {
    return children;
  }
});

Skeleton.displayName = 'Skeleton';
SkeletonText.displayName = 'SkeletonText';

export { Skeleton, SkeletonText };
