import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from '../services/auth.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const key = inject(AuthService).apiKey();
  if (key) {
    console.log('[AuthInterceptor] Adding logo-key header to', req.url);
    return next(req.clone({ setHeaders: { 'logos-key': key } }));
  }
  console.log('[AuthInterceptor] No API key for', req.url);
  return next(req);
};
