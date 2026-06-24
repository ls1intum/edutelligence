import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { Model, AddModelPayload, UpdateModelPayload } from '../../shared/models/model.model';

@Injectable({ providedIn: 'root' })
export class ModelManagementService {
  private http = inject(HttpClient);

  getModels(): Promise<Model[]> {
    return firstValueFrom(this.http.post<Model[]>('/api/logosdb/get_models', {}));
  }

  addModel(payload: AddModelPayload): Promise<Model> {
    return firstValueFrom(this.http.post<Model>('/api/logosdb/add_model', payload));
  }

  updateModel(payload: UpdateModelPayload): Promise<Model> {
    return firstValueFrom(this.http.post<Model>('/api/logosdb/update_model_info', payload));
  }

  deleteModel(id: number): Promise<void> {
    return firstValueFrom(this.http.post<void>('/api/logosdb/delete_model', { id }));
  }
}
