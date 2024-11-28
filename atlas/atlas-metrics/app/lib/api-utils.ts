import { EnumLike, z } from "zod";
import { NextResponse } from "next/server";

export const SearchParamStringOrUndefined = (searchParams: URLSearchParams, key: string) => {
  const value = searchParams.get(key);
  return value ? value : undefined;
};

export const SearchParamEnumOrUndefined = <T extends EnumLike>(
  searchParams: URLSearchParams,
  key: string,
  enumType: T,
) => {
  const value = searchParams.get(key);
  if (!value) {
    return undefined;
  }
  const parsed = z.nativeEnum(enumType).safeParse(value);
  if (!parsed.success) {
    throw new Error(`Invalid enum value in query parameter ${key}: ${parsed.error}`);
  }
  return parsed.data;
};

export const SearchParamDateOrUndefined = (searchParams: URLSearchParams, key: string) => {
  const value = searchParams.get(key);
  if (!value) {
    return undefined;
  }
  const parsed = z.date().safeParse(value);
  if (!parsed.success) {
    throw new Error(`Invalid date format in query parameter ${key}: ${parsed.error}`);
  }
  return parsed.data;
};

export const ErrorResponse = (error: unknown, status: number) =>
  NextResponse.json(
    { error: error?.toString() || "An unknown error occurred" },
    { status: status },
  );
